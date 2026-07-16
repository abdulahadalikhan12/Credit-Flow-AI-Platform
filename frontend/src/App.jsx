import React, { useState, useEffect, useRef } from 'react';
import { 
  LayoutDashboard, FileText, Calendar as CalendarIcon, Users, CreditCard, 
  ShoppingBag, Shield, LogOut, CheckCircle2, AlertTriangle, Play, Image as ImageIcon,
  Clock, Plus, RefreshCw, X, User, ChevronDown, Trash2, Send, Search, Sparkles
} from 'lucide-react';

const API_BASE = 'http://localhost:8000/api/v1';

export default function App() {
  // Navigation & Auth State
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [user, setUser] = useState(null);
  const [currentAccount, setCurrentAccount] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [currentPage, setCurrentPage] = useState('home'); // home, login, signup, dashboard, etc.
  
  // UI States
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [showAccountDropdown, setShowAccountDropdown] = useState(false);
  
  // Forms state
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [otpToken, setOtpToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  
  const [prompt, setPrompt] = useState('');
  const [aiModel, setAiModel] = useState('gemini');
  const [aiImageModel, setAiImageModel] = useState('flux');
  const [generatedText, setGeneratedText] = useState('');
  const [generatedImageUrl, setGeneratedImageUrl] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [contentTitle, setContentTitle] = useState('');
  
  // Content & Calendar State
  const [posts, setPosts] = useState([]);
  const [selectedPostId, setSelectedPostId] = useState('');
  const [scheduleDate, setScheduleDate] = useState('');
  const [repeatCadence, setRepeatCadence] = useState('none');
  const [calendarPosts, setCalendarPosts] = useState([]);
  
  // Billing & Marketplace State
  const [balance, setBalance] = useState(0);
  const [ledger, setLedger] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [marketListings, setMarketListings] = useState([]);
  const [sellCreditsAmount, setSellCreditsAmount] = useState(10);
  const [sellCreditsPrice, setSellCreditsPrice] = useState(100); // in cents
  
  // Team State
  const [members, setMembers] = useState([]);
  
  // Admin State
  const [activeSessions, setActiveSessions] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [auditSearch, setAuditSearch] = useState('');

  // Sandbox Simulator, Dynamic Calendar & Connections states
  const [mockCheckout, setMockCheckout] = useState(null); // { account_id, plan_tier } or null
  const [successModal, setSuccessModal] = useState('');
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selectedCalendarEvent, setSelectedCalendarEvent] = useState(null);
  const [rescheduleDate, setRescheduleDate] = useState('');
  const [connections, setConnections] = useState([]);
  const [socialHistory, setSocialHistory] = useState([]);
  const [adminWorkspaces, setAdminWorkspaces] = useState([]);
  const [selectedWorkspaceDetails, setSelectedWorkspaceDetails] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null);

  // Mock Card Form State for Stripe Sandbox
  const [mockCardName, setMockCardName] = useState('');
  const [mockCardNumber, setMockCardNumber] = useState('');
  const [mockCardExpiry, setMockCardExpiry] = useState('');
  const [mockCardCvc, setMockCardCvc] = useState('');

  // Handle auto email verification, invite link and Stripe Sandbox simulation parameters
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const isInvite = window.location.pathname.includes('/invite');
    
    const tokenParam = params.get('token');
    if (tokenParam) {
      window.history.replaceState({}, document.title, '/');
      if (isInvite) {
        // Handle member invitation!
        localStorage.setItem('pending_invite_token', tokenParam);
        setInfo('Invitation token captured. Please log in or register to join the workspace.');
        setCurrentPage('login');
      } else {
        // Handle email verification
        const verifyToken = async () => {
          setError('');
          setInfo('Verifying email...');
          try {
            const res = await fetch(`${API_BASE}/auth/verify-email`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ token: tokenParam })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Verification failed');
            setInfo('Email verified successfully! You can now log in.');
            setCurrentPage('login');
          } catch (err) {
            setError(err.message);
            setInfo('');
          }
        };
        verifyToken();
      }
    }
    
    const mockParam = params.get('mock_checkout');
    const accIdParam = params.get('account_id');
    const tierParam = params.get('plan_tier');
    if (mockParam === 'true' && accIdParam && tierParam) {
      window.history.replaceState({}, document.title, window.location.pathname);
      setMockCheckout({
        account_id: accIdParam,
        plan_tier: tierParam
      });
    }
    
    const billingParam = params.get('billing');
    if (billingParam === 'success') {
      window.history.replaceState({}, document.title, window.location.pathname);
      setSuccessModal("Payment Completed Successfully! Your credits will be updated shortly.");
      fetchCreditsBalance();
      fetchInvoices();
    } else if (billingParam === 'cancel') {
      window.history.replaceState({}, document.title, window.location.pathname);
      setError("Stripe Checkout was cancelled.");
    }
  }, []);

  // Enforce client-side role guards & routing synchronization
  useEffect(() => {
    const guestPages = ['home', 'login', 'signup', 'forgot-password', 'reset-password'];
    if (token) {
      if (guestPages.includes(currentPage)) {
        setCurrentPage('dashboard');
      }
      if (['admin-sessions', 'admin-audit', 'admin-workspaces'].includes(currentPage)) {
        if (user && user.role !== 'superadmin') {
          setCurrentPage('dashboard');
          setError('Access denied: SuperAdmin privileges required.');
        }
      }
      if (currentPage === 'billing') {
        if (currentAccount && currentAccount.role !== 'owner') {
          setCurrentPage('dashboard');
          setError('Access denied: Only the workspace Owner can access Billing.');
        }
      }
    } else {
      if (!guestPages.includes(currentPage)) {
        setCurrentPage('home');
      }
    }
  }, [currentPage, user, currentAccount, token]);

  // Handle accepting invitations automatically if logged in
  const handleAcceptInvite = async (inviteToken) => {
    setError('');
    setInfo('Accepting workspace invitation...');
    try {
      const res = await fetch(`${API_BASE}/accounts/invite/accept`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ token: inviteToken })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to accept invitation');
      
      localStorage.removeItem('pending_invite_token');
      setInfo('Workspace invitation accepted successfully!');
      await fetchUserAccounts();
      setCurrentPage('dashboard');
    } catch (err) {
      setError(err.message);
      localStorage.removeItem('pending_invite_token');
    }
  };

  useEffect(() => {
    if (token && user) {
      const pendingInvite = localStorage.getItem('pending_invite_token');
      if (pendingInvite) {
        handleAcceptInvite(pendingInvite);
      }
    }
  }, [token, user]);

  // Extract User Profile from JWT (Base64 decode payload)
  useEffect(() => {
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        setUser({
          user_id: payload.user_id,
          email: payload.email || 'user@local.dev',
          role: payload.role
        });
        localStorage.setItem('token', token);
        fetchUserAccounts();
      } catch (e) {
        console.error("Token decoding error", e);
        handleLogout();
      }
    } else {
      setUser(null);
      setCurrentAccount(null);
      setAccounts([]);
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      if (currentPage !== 'signup' && currentPage !== 'forgot-password') {
        setCurrentPage('home');
      }
    }
  }, [token]);

  // Sync details on active workspace switch
  useEffect(() => {
    if (currentAccount && token) {
      fetchDashboardData();
    }
  }, [currentAccount, token]);

  // Request Headers Helper
  const getHeaders = () => {
    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    };
    return headers;
  };

  // Auth Operations
  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Login failed');
      localStorage.setItem('refresh_token', data.refresh_token);
      setToken(data.access_token);
      setCurrentPage('dashboard');
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${API_BASE}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Signup failed');
      setInfo('Signup successful! Please check your email or click below to simulate verification.');
      // Auto fill token with verification simulation
      setOtpToken(data.id); // for direct link verification simulation
    } catch (err) {
      setError(err.message);
    }
  };

  const simulateVerification = async () => {
    setError('');
    try {
      const res = await fetch(`${API_BASE}/auth/verify-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: otpToken })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Verification failed');
      setInfo('Email verified successfully! You can now log in.');
      setCurrentPage('login');
    } catch (err) {
      setError(err.message);
    }
  };

  const handleForgotPassword = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${API_BASE}/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setInfo('Password reset code (OTP) sent to your email.');
      setCurrentPage('reset-password');
    } catch (err) {
      setError(err.message);
    }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${API_BASE}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, token: otpToken, new_password: newPassword })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setInfo('Password updated successfully! Please log in.');
      setCurrentPage('login');
    } catch (err) {
      setError(err.message);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('refresh_token');
    setToken('');
    setUser(null);
    setCurrentAccount(null);
    setCurrentPage('home');
  };

  // Switch Workspace Account
  const handleAccountSwitch = async (acc) => {
    setError('');
    const refreshToken = localStorage.getItem('refresh_token') || '';
    try {
      const res = await fetch(`${API_BASE}/auth/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: acc.account_id, refresh_token: refreshToken })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Switching workspace failed');
      
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      setToken(data.access_token);
      setCurrentAccount(acc);
      setShowAccountDropdown(false);
      setInfo(`Switched workspace to ${acc.name}`);
    } catch (err) {
      setError(err.message);
    }
  };

  // API Fetches
  const fetchUserAccounts = async () => {
    try {
      const res = await fetch(`${API_BASE}/accounts/switch`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setAccounts(data);
        if (data.length > 0 && !currentAccount) {
          setCurrentAccount(data[0]);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchDashboardData = async () => {
    if (!currentAccount) return;
    fetchPosts();
    fetchCreditsBalance();
    fetchInvoices();
    fetchMarketplaceListings();
    fetchTeamMembers();
    if (user?.role === 'superadmin' || currentAccount.role === 'owner') {
      fetchAdminSessions();
      fetchAuditLogs();
    }
  };

  const fetchCalendarPosts = async () => {
    if (!currentAccount) return;
    try {
      const year = currentMonth.getFullYear();
      const month = currentMonth.getMonth();
      const startDateStr = `${year}-${String(month + 1).padStart(2, '0')}-01`;
      const lastDay = new Date(year, month + 1, 0).getDate();
      const endDateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
      
      const res = await fetch(`${API_BASE}/scheduler/calendar?start_date=${startDateStr}&end_date=${endDateStr}`, { headers: getHeaders() });
      if (res.ok) {
        setCalendarPosts(await res.json());
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchSocialData = async () => {
    if (!currentAccount) return;
    try {
      const connRes = await fetch(`${API_BASE}/social/connections`, { headers: getHeaders() });
      if (connRes.ok) setConnections(await connRes.json());
      
      const histRes = await fetch(`${API_BASE}/social/history`, { headers: getHeaders() });
      if (histRes.ok) setSocialHistory(await histRes.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchAdminWorkspaces = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/workspaces`, { headers: getHeaders() });
      if (res.ok) {
        setAdminWorkspaces(await res.json());
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (currentPage === 'calendar' && currentAccount) {
      fetchCalendarPosts();
    }
  }, [currentMonth, currentAccount, currentPage]);

  useEffect(() => {
    if (currentPage === 'social-integrations' && currentAccount) {
      fetchSocialData();
    }
  }, [currentPage, currentAccount]);

  useEffect(() => {
    if (currentPage === 'admin-workspaces' && user?.role === 'superadmin') {
      fetchAdminWorkspaces();
    }
    if (currentPage === 'admin-sessions' && user?.role === 'superadmin') {
      fetchAdminSessions();
    }
    if (currentPage === 'admin-audit' && user?.role === 'superadmin') {
      fetchAuditLogs();
    }
  }, [currentPage, user]);

  const triggerConfirmation = (message, onConfirm) => {
    setConfirmAction({
      message,
      onConfirm: () => {
        onConfirm();
        setConfirmAction(null);
      }
    });
  };

  const handleAuthorizeSimulatedPayment = async () => {
    if (!mockCheckout) return;
    setError('');
    setInfo('');
    try {
      const payload = {
        event_type: "invoice.paid",
        body: {
          account_id: mockCheckout.account_id,
          customer_id: `cus_mock_${mockCheckout.account_id.slice(0, 8)}`,
          subscription_id: `sub_mock_${Math.random().toString(36).substring(2, 10)}`,
          plan_tier: mockCheckout.plan_tier,
          amount_paid: mockCheckout.plan_tier.startsWith("credits_") 
            ? (mockCheckout.plan_tier === "credits_100" ? 500 : mockCheckout.plan_tier === "credits_500" ? 2000 : 3500)
            : (mockCheckout.plan_tier === "pro" ? 1900 : 4900)
        }
      };
      
      const res = await fetch(`${API_BASE}/billing/webhook/stripe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Simulator webhook call failed.");
      
      setMockCheckout(null);
      setSuccessModal("Simulated Payment webhook sent successfully! Credits should update in a few seconds.");
      fetchCreditsBalance();
      setTimeout(fetchCreditsBalance, 2000);
      fetchInvoices();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSocialDisconnect = async () => {
    triggerConfirmation("Are you sure you want to disconnect your LinkedIn profile?", async () => {
      setError('');
      try {
        const res = await fetch(`${API_BASE}/social/disconnect`, {
          method: 'POST',
          headers: getHeaders()
        });
        if (res.ok) {
          setInfo("Successfully disconnected LinkedIn connection.");
          fetchSocialData();
        }
      } catch (e) {
        setError("Failed to disconnect LinkedIn connection.");
      }
    });
  };

  const handleCancelSchedule = async (scheduleId) => {
    triggerConfirmation("Are you sure you want to cancel this scheduled post?", async () => {
      setError('');
      try {
        const res = await fetch(`${API_BASE}/scheduler/cancel/${scheduleId}`, {
          method: 'POST',
          headers: getHeaders()
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Failed to cancel schedule');
        }
        setInfo('Schedule canceled successfully.');
        setSelectedCalendarEvent(null);
        fetchCalendarPosts();
      } catch (err) {
        setError(err.message);
      }
    });
  };

  const handleReschedulePost = async (e) => {
    e.preventDefault();
    if (!selectedCalendarEvent || !rescheduleDate) return;
    setError('');
    try {
      const res = await fetch(`${API_BASE}/scheduler/reschedule/${selectedCalendarEvent.id}?publish_at=${encodeURIComponent(new Date(rescheduleDate).toISOString())}`, {
        method: 'POST',
        headers: getHeaders()
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to reschedule post');
      }
      setInfo('Post rescheduled successfully!');
      setSelectedCalendarEvent(null);
      setRescheduleDate('');
      fetchCalendarPosts();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleRemoveMember = async (memberId) => {
    triggerConfirmation("Are you sure you want to remove this member from the workspace?", async () => {
      setError('');
      try {
        const res = await fetch(`${API_BASE}/accounts/members/${memberId}`, {
          method: 'DELETE',
          headers: getHeaders()
        });
        if (res.ok) {
          setInfo("Member removed successfully.");
          fetchTeamMembers();
        } else {
          const data = await res.json();
          throw new Error(data.detail || "Failed to remove member");
        }
      } catch (err) {
        setError(err.message);
      }
    });
  };

  const fetchPosts = async () => {
    try {
      const res = await fetch(`${API_BASE}/content`, { headers: getHeaders() });
      if (res.ok) setPosts(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchCreditsBalance = async () => {
    try {
      const res = await fetch(`${API_BASE}/credits/balance`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setBalance(data.balance);
        setLedger(data.ledger);
      }
    } catch (e) { console.error(e); }
  };

  const fetchInvoices = async () => {
    if (currentAccount?.role !== 'owner') return;
    try {
      const res = await fetch(`${API_BASE}/billing/invoices`, { headers: getHeaders() });
      if (res.ok) setInvoices(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchMarketplaceListings = async () => {
    try {
      const res = await fetch(`${API_BASE}/credits/marketplace/listings`, { headers: getHeaders() });
      if (res.ok) setMarketListings(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchTeamMembers = async () => {
    try {
      const res = await fetch(`${API_BASE}/accounts/members`, { headers: getHeaders() });
      if (res.ok) setMembers(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchAdminSessions = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/sessions`, { headers: getHeaders() });
      if (res.ok) setActiveSessions(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchAuditLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/audit-log`, { headers: getHeaders() });
      if (res.ok) setAuditLogs(await res.json());
    } catch (e) { console.error(e); }
  };

  // AI Content Generation (SSE Stream)
  const triggerAiTextGeneration = async () => {
    if (!prompt) return;
    setError('');
    setGeneratedText('');
    setGeneratedImageUrl('');
    setIsGenerating(true);

    try {
      const res = await fetch(`${API_BASE}/ai/generate`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ prompt, model: aiModel })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Generation failed');

      const jobId = data.job_id;
      // Connect to Gateway SSE Stream
      const eventSource = new EventSource(`http://localhost:8000/api/v1/ai/stream/${jobId}`);
      
      eventSource.addEventListener('token', (e) => {
        setGeneratedText((prev) => prev + e.data);
      });

      eventSource.addEventListener('done', () => {
        eventSource.close();
        setIsGenerating(false);
        setInfo('AI text generation completed!');
        fetchCreditsBalance();
        fetchPosts(); // reload drafts
      });

      eventSource.addEventListener('error', (e) => {
        eventSource.close();
        setIsGenerating(false);
        setError('Error streaming response from AI core.');
      });

    } catch (err) {
      setError(err.message);
      setIsGenerating(false);
    }
  };

  // AI Image Generation
  const triggerAiImageGeneration = async () => {
    if (!prompt) return;
    setError('');
    setIsGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/ai/generate-image`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ prompt, model: aiImageModel })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setGeneratedImageUrl(data.image_url);
      setInfo('AI image generated successfully!');
      fetchCreditsBalance();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsGenerating(false);
    }
  };

  // Save draft post
  const saveDraftPost = async () => {
    if (!generatedText) return;
    setError('');
    try {
      const res = await fetch(`${API_BASE}/content`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          title: contentTitle || `AI Draft ${new Date().toLocaleDateString()}`,
          body: generatedText,
          image_url: generatedImageUrl || null
        })
      });
      if (res.ok) {
        setInfo('Draft post saved successfully!');
        fetchPosts();
      }
    } catch (e) {
      setError('Failed to save draft.');
    }
  };

  // Upload Manual Image
  const handleImageUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    
    setError('');
    try {
      const res = await fetch(`${API_BASE}/content/upload-image`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        },
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        setGeneratedImageUrl(data.image_url);
        setInfo('Image uploaded successfully!');
      }
    } catch (err) {
      setError('Image upload failed.');
    }
  };

  // Scheduling Calendar
  const handleSchedulePost = async (e) => {
    e.preventDefault();
    if (!selectedPostId || !scheduleDate) return;
    setError('');
    try {
      const res = await fetch(`${API_BASE}/scheduler/schedule`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          content_id: selectedPostId,
          publish_at: new Date(scheduleDate).toISOString(),
          repeat_cadence: repeatCadence
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setInfo('Content scheduled successfully!');
      fetchDashboardData();
    } catch (err) {
      setError(err.message);
    }
  };

  // Billing subscriptions Checkout
  const handleUpgradeSubscription = async (tier) => {
    setError('');
    try {
      const res = await fetch(`${API_BASE}/billing/checkout`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ plan_tier: tier })
      });
      const data = await res.json();
      if (res.ok && data.checkout_url) {
        // Redirect to Stripe checkout page
        window.location.href = data.checkout_url;
      }
    } catch (e) {
      setError('Subscription checkout failed.');
    }
  };

  // Marketplace Sell Credits
  const handleListCredits = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${API_BASE}/credits/marketplace/list`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ amount: sellCreditsAmount, price: sellCreditsPrice })
      });
      if (res.ok) {
        setInfo('Credits listed for sale in marketplace!');
        fetchCreditsBalance();
        fetchMarketplaceListings();
      }
    } catch (e) {
      setError('Failed to list credits.');
    }
  };

  // Marketplace Buy Credits
  const handleBuyCredits = async (listingId) => {
    setError('');
    try {
      const res = await fetch(`${API_BASE}/credits/marketplace/buy/${listingId}`, {
        method: 'POST',
        headers: getHeaders()
      });
      if (res.ok) {
        setInfo('Credits purchased successfully!');
        fetchCreditsBalance();
        fetchMarketplaceListings();
      }
    } catch (e) {
       setError('Purchase failed.');
    }
  };

  // Team Invite Member
  const handleInviteMember = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${API_BASE}/accounts/invite`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ email: inviteEmail, role: inviteRole })
      });
      if (res.ok) {
        setInfo('Invitation sent successfully!');
        setInviteEmail('');
      }
    } catch (e) {
      setError('Failed to send invitation.');
    }
  };

  // Admin Sessions Revoke
  const handleRevokeSession = async (jti) => {
    triggerConfirmation("Are you sure you want to revoke this user's active session?", async () => {
      try {
        const res = await fetch(`${API_BASE}/admin/sessions/${jti}`, {
          method: 'DELETE',
          headers: getHeaders()
        });
        if (res.ok) {
          setInfo('Session revoked successfully.');
          fetchAdminSessions();
        }
      } catch (e) { console.error(e); }
    });
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* HEADER BAR */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Sparkles className="h-7 w-7 text-indigo-500 animate-pulse" />
          <h1 className="text-xl font-bold tracking-wider bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
            CreditFlow AI
          </h1>
        </div>

        {user && (
          <div className="flex items-center gap-4">
            {/* Account Switcher */}
            <div className="relative">
              <button 
                onClick={() => setShowAccountDropdown(!showAccountDropdown)}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 transition"
              >
                <span>{currentAccount?.name || 'Workspace'}</span>
                <span className="text-xs uppercase bg-indigo-900/80 px-2 py-0.5 rounded text-indigo-300">
                  {currentAccount?.plan_tier}
                </span>
                <ChevronDown className="h-4 w-4 text-slate-400" />
              </button>

              {showAccountDropdown && (
                <div className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-800 bg-slate-900 p-2 shadow-2xl z-50">
                  <div className="px-3 py-1.5 text-xs text-slate-500 font-semibold border-b border-slate-800 mb-2">
                    Switch Workspace
                  </div>
                  {accounts.map((acc) => (
                    <button
                      key={acc.account_id}
                      onClick={() => handleAccountSwitch(acc)}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-left text-sm transition hover:bg-slate-800 ${
                        currentAccount?.account_id === acc.account_id ? 'bg-indigo-950/40 text-indigo-400' : ''
                      }`}
                    >
                      <span className="truncate">{acc.name}</span>
                      <span className="text-xs text-slate-500">{acc.role}</span>
                    </button>
                  ))}
                  <div className="border-t border-slate-800 mt-2 pt-2">
                    <button 
                      onClick={() => setCurrentPage('create-team')}
                      className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-sm text-indigo-400 hover:bg-slate-800"
                    >
                      <Plus className="h-4 w-4" />
                      Create Team Workspace
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Profile & Logout */}
            <div className="flex items-center gap-3 pl-4 border-l border-slate-800">
              <span className="text-sm text-slate-400 truncate max-w-[150px]">{user.email}</span>
              <button 
                onClick={handleLogout}
                className="p-2 rounded-lg bg-slate-800 text-red-400 hover:bg-red-950/20 hover:text-red-300 border border-slate-700 transition"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </header>

      {/* CORE WORKSPACE CONTENT */}
      <div className="flex flex-1">
        {/* SIDE NAVIGATION */}
        {user && (
          <aside className="w-64 border-r border-slate-800 bg-slate-900/30 p-4 flex flex-col gap-2">
            <button
              onClick={() => setCurrentPage('dashboard')}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                currentPage === 'dashboard' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'hover:bg-slate-800 text-slate-400'
              }`}
            >
              <LayoutDashboard className="h-5 w-5" />
              Dashboard
            </button>
            <button
              onClick={() => setCurrentPage('content-studio')}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                currentPage === 'content-studio' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'hover:bg-slate-800 text-slate-400'
              }`}
            >
              <FileText className="h-5 w-5" />
              Content Studio
            </button>
            <button
              onClick={() => setCurrentPage('calendar')}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                currentPage === 'calendar' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'hover:bg-slate-800 text-slate-400'
              }`}
            >
              <CalendarIcon className="h-5 w-5" />
              Scheduler
            </button>
            <button
              onClick={() => setCurrentPage('marketplace')}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                currentPage === 'marketplace' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'hover:bg-slate-800 text-slate-400'
              }`}
            >
              <ShoppingBag className="h-5 w-5" />
              Marketplace
            </button>
            {currentAccount?.role === 'owner' && (
              <button
                onClick={() => setCurrentPage('billing')}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                  currentPage === 'billing' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'hover:bg-slate-800 text-slate-400'
                }`}
              >
                <CreditCard className="h-5 w-5" />
                Billing
              </button>
            )}
            <button
              onClick={() => setCurrentPage('team')}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                currentPage === 'team' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'hover:bg-slate-800 text-slate-400'
              }`}
            >
              <Users className="h-5 w-5" />
              Team Management
            </button>
            <button
              onClick={() => setCurrentPage('social-integrations')}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                currentPage === 'social-integrations' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'hover:bg-slate-800 text-slate-400'
              }`}
            >
              <RefreshCw className="h-5 w-5" />
              LinkedIn Connection
            </button>

            {/* Admin console links */}
            {user.role === 'superadmin' && (
              <div className="mt-8 pt-6 border-t border-slate-800 flex flex-col gap-2">
                <span className="px-4 text-xs font-bold text-slate-500 uppercase tracking-widest">
                  Admin Console
                </span>
                <button
                  onClick={() => setCurrentPage('admin-workspaces')}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                    currentPage === 'admin-workspaces' ? 'bg-purple-600 text-white' : 'hover:bg-slate-800 text-slate-400'
                  }`}
                >
                  <Users className="h-5 w-5" />
                  Workspaces Directory
                </button>
                <button
                  onClick={() => setCurrentPage('admin-sessions')}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                    currentPage === 'admin-sessions' ? 'bg-purple-600 text-white' : 'hover:bg-slate-800 text-slate-400'
                  }`}
                >
                  <Shield className="h-5 w-5" />
                  Active Sessions
                </button>
                <button
                  onClick={() => setCurrentPage('admin-audit')}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl transition ${
                    currentPage === 'admin-audit' ? 'bg-purple-600 text-white' : 'hover:bg-slate-800 text-slate-400'
                  }`}
                >
                  <Clock className="h-5 w-5" />
                  Audit Trail
                </button>
              </div>
            )}
          </aside>
        )}

        {/* MAIN BODY WINDOW */}
        <main className="flex-1 p-8 overflow-y-auto max-w-7xl mx-auto w-full">
          {/* Notifications */}
          {error && (
            <div className="mb-6 p-4 rounded-xl border border-red-800/40 bg-red-950/20 text-red-300 flex items-center gap-3">
              <AlertTriangle className="h-5 w-5" />
              <span>{error}</span>
            </div>
          )}
          {info && (
            <div className="mb-6 p-4 rounded-xl border border-emerald-800/40 bg-emerald-950/20 text-emerald-300 flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5" />
              <span>{info}</span>
              <button onClick={() => setInfo('')} className="ml-auto text-slate-400 hover:text-slate-200">
                <X className="h-4 w-4" />
              </button>
            </div>
          )}

          {/* PAGE ROUTER CONTROLLER */}
          {currentPage === 'home' && (
            <div className="py-20 text-center max-w-3xl mx-auto flex flex-col items-center">
              <Sparkles className="h-16 w-16 text-indigo-500 mb-6 animate-bounce" />
              <h2 className="text-5xl font-extrabold tracking-tight mb-4 bg-gradient-to-r from-white via-indigo-200 to-indigo-400 bg-clip-text text-transparent">
                Asynchronous, Multi-Tenant AI Content Publisher
              </h2>
              <p className="text-slate-400 text-lg mb-8 leading-relaxed">
                Unlock automated streaming completions, versioned drafts, marketplace peer-to-peer credit trading, and scheduled publishing straight to LinkedIn.
              </p>
              <div className="flex gap-4">
                <button 
                  onClick={() => setCurrentPage('login')}
                  className="px-8 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 font-semibold transition"
                >
                  Log In
                </button>
                <button 
                  onClick={() => setCurrentPage('signup')}
                  className="px-8 py-3 rounded-xl bg-slate-800 hover:bg-slate-700 font-semibold transition"
                >
                  Register Account
                </button>
              </div>
            </div>
          )}

          {currentPage === 'login' && (
            <div className="max-w-md mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl">
              <h2 className="text-2xl font-bold mb-6 text-center">Log In to CreditFlow</h2>
              <form onSubmit={handleLogin} className="flex flex-col gap-4">
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Email</label>
                  <input 
                    type="email" 
                    required 
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                    placeholder="you@email.com"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Password</label>
                  <input 
                    type="password" 
                    required 
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                  />
                </div>
                <button 
                  type="submit" 
                  className="mt-2 bg-indigo-600 hover:bg-indigo-500 font-semibold rounded-lg py-2.5 transition"
                >
                  Log In
                </button>
              </form>
              <div className="mt-4 text-center text-sm text-slate-500 flex flex-col gap-2">
                <button onClick={() => setCurrentPage('forgot-password')} className="text-indigo-400 hover:underline">
                  Forgot Password?
                </button>
                <span>Don't have an account? <button onClick={() => setCurrentPage('signup')} className="text-indigo-400 hover:underline">Sign up</button></span>
              </div>
            </div>
          )}

          {currentPage === 'signup' && (
            <div className="max-w-md mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl">
              <h2 className="text-2xl font-bold mb-6 text-center">Create your Account</h2>
              <form onSubmit={handleSignup} className="flex flex-col gap-4">
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Email</label>
                  <input 
                    type="email" 
                    required 
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                    placeholder="you@email.com"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Password (6+ chars)</label>
                  <input 
                    type="password" 
                    required 
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                  />
                </div>
                <button 
                  type="submit" 
                  className="mt-2 bg-indigo-600 hover:bg-indigo-500 font-semibold rounded-lg py-2.5 transition"
                >
                  Sign Up
                </button>
              </form>
              {otpToken && (
                <div className="mt-6 border-t border-slate-800 pt-4 flex flex-col gap-3">
                  <span className="text-xs text-indigo-300 block">
                    [Sandbox Link Verification]: Auto-extracted verification code:
                  </span>
                  <input 
                    type="text" 
                    value={otpToken} 
                    onChange={(e) => setOtpToken(e.target.value)}
                    className="bg-slate-950 border border-slate-800 text-xs text-slate-400 p-2 rounded"
                  />
                  <button 
                    onClick={simulateVerification}
                    className="bg-emerald-600 hover:bg-emerald-500 font-semibold text-xs py-2 rounded transition"
                  >
                    Complete Sandbox Verification Link Click
                  </button>
                </div>
              )}
              <div className="mt-4 text-center text-sm text-slate-500">
                Already have an account? <button onClick={() => setCurrentPage('login')} className="text-indigo-400 hover:underline">Log in</button>
              </div>
            </div>
          )}

          {currentPage === 'forgot-password' && (
            <div className="max-w-md mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl">
              <h2 className="text-2xl font-bold mb-6 text-center">Forgot Password</h2>
              <form onSubmit={handleForgotPassword} className="flex flex-col gap-4">
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Email</label>
                  <input 
                    type="email" 
                    required 
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                  />
                </div>
                <button 
                  type="submit" 
                  className="mt-2 bg-indigo-600 hover:bg-indigo-500 font-semibold rounded-lg py-2.5 transition"
                >
                  Send OTP Code
                </button>
              </form>
            </div>
          )}

          {currentPage === 'reset-password' && (
            <div className="max-w-md mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl">
              <h2 className="text-2xl font-bold mb-6 text-center">Reset Password</h2>
              <form onSubmit={handleResetPassword} className="flex flex-col gap-4">
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Verification OTP</label>
                  <input 
                    type="text" 
                    required 
                    value={otpToken}
                    onChange={(e) => setOtpToken(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">New Password</label>
                  <input 
                    type="password" 
                    required 
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                  />
                </div>
                <button 
                  type="submit" 
                  className="mt-2 bg-indigo-600 hover:bg-indigo-500 font-semibold rounded-lg py-2.5 transition"
                >
                  Update Password
                </button>
              </form>
            </div>
          )}

          {currentPage === 'dashboard' && (
            <div className="flex flex-col gap-8">
              {/* Workspace Header Cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 flex flex-col gap-2">
                  <span className="text-xs uppercase text-slate-500 font-semibold">Active Plan</span>
                  <span className="text-3xl font-extrabold text-indigo-400 capitalize">{currentAccount?.plan_tier}</span>
                </div>
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 flex flex-col gap-2">
                  <span className="text-xs uppercase text-slate-500 font-semibold">Credits Balance</span>
                  <span className="text-3xl font-extrabold text-emerald-400">{balance} credits</span>
                </div>
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 flex flex-col gap-2">
                  <span className="text-xs uppercase text-slate-500 font-semibold">Draft Posts</span>
                  <span className="text-3xl font-extrabold text-blue-400">{posts.length}</span>
                </div>
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 flex flex-col gap-2">
                  <span className="text-xs uppercase text-slate-500 font-semibold">Team Members</span>
                  <span className="text-3xl font-extrabold text-purple-400">{members.length}</span>
                </div>
              </div>

              {/* Sandbox integrations simulation alerts */}
              <div className="bg-indigo-950/20 border border-indigo-800/40 rounded-2xl p-6">
                <h3 className="text-lg font-bold mb-2 flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-indigo-400" />
                  Social Connection: LinkedIn OAuth Sandbox Simulation
                </h3>
                <p className="text-slate-400 text-sm mb-4">
                  Connect your simulated LinkedIn developer portal. In mock mode, posts are printed directly to the system logs and saved as successful UGC shares.
                </p>
                <button
                  onClick={async () => {
                    const res = await fetch(`${API_BASE}/social/connect/linkedin`, { headers: getHeaders() });
                    const data = await res.json();
                    if (data.authorization_url) window.location.href = data.authorization_url;
                  }}
                  className="bg-indigo-600 hover:bg-indigo-500 font-semibold rounded-lg px-6 py-2.5 transition text-sm"
                >
                  Connect LinkedIn Workspace Account
                </button>
              </div>

              {/* Draft Posts Log */}
              <div>
                <h3 className="text-lg font-bold mb-4">Recent Draft Content</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {posts.map((post) => (
                    <div key={post.id} className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col justify-between">
                      <div>
                        <span className="text-xs uppercase font-bold px-2 py-0.5 rounded bg-indigo-900/50 text-indigo-400 inline-block mb-3">
                          {post.status}
                        </span>
                        <h4 className="font-bold text-lg mb-2">{post.title}</h4>
                        <p className="text-slate-400 text-sm line-clamp-3 mb-4">{post.body}</p>
                      </div>
                      <div className="flex gap-2 border-t border-slate-800 pt-4">
                        <button 
                          onClick={() => {
                            setSelectedPostId(post.id);
                            setCurrentPage('calendar');
                          }}
                          className="flex-1 bg-slate-800 hover:bg-slate-700 text-xs font-semibold py-2 rounded-lg text-center transition"
                        >
                          Schedule Post
                        </button>
                      </div>
                    </div>
                  ))}
                  {posts.length === 0 && (
                    <p className="text-slate-500 italic text-sm">No content drafts. Head to the Content Studio to generate some!</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {currentPage === 'content-studio' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {/* Left Column: Generator Controls */}
              <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-8 flex flex-col gap-6">
                <h3 className="text-xl font-bold flex items-center gap-2 text-indigo-400">
                  <Sparkles className="h-5 w-5" />
                  Content Studio
                </h3>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">AI Text Model</label>
                    <select 
                      value={aiModel} 
                      onChange={(e) => setAiModel(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                    >
                      <option value="gemini">Gemini 2.5 Flash (1 Cr)</option>
                      <option value="llama">Llama 3 8B (1 Cr)</option>
                      <option value="mistral">Mistral 7B (1 Cr)</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">AI Image Model</label>
                    <select 
                      value={aiImageModel} 
                      onChange={(e) => setAiImageModel(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                    >
                      <option value="flux">Flux (High Quality)</option>
                      <option value="turbo">Turbo (Fast)</option>
                      <option value="anime">Anime (Artistic)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Title</label>
                  <input 
                    type="text" 
                    value={contentTitle} 
                    onChange={(e) => setContentTitle(e.target.value)}
                    placeholder="Enter draft title (optional)"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                  />
                </div>

                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Prompt</label>
                  <textarea 
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={6}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none resize-none"
                    placeholder="Describe what you want to write or generate..."
                  />
                </div>

                <div className="flex gap-4">
                  <button 
                    onClick={triggerAiTextGeneration}
                    disabled={isGenerating}
                    className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 font-semibold rounded-lg py-2.5 transition flex items-center justify-center gap-2"
                  >
                    <Play className="h-4 w-4" />
                    {isGenerating ? 'Streaming...' : 'Generate Text'}
                  </button>

                  <button 
                    onClick={triggerAiImageGeneration}
                    disabled={isGenerating}
                    className="flex-1 bg-slate-800 hover:bg-slate-700 disabled:bg-slate-800 font-semibold rounded-lg py-2.5 border border-slate-700 transition flex items-center justify-center gap-2"
                  >
                    <ImageIcon className="h-4 w-4" />
                    Generate Image (10 Cr)
                  </button>
                </div>

                <div className="border-t border-slate-800 pt-4">
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-2">Or Upload Image Manually</label>
                  <input 
                    type="file" 
                    accept="image/*" 
                    onChange={handleImageUpload}
                    className="text-sm text-slate-500"
                  />
                </div>
              </div>

              {/* Right Column: Generation Outputs */}
              <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-8 flex flex-col gap-6">
                <h3 className="text-xl font-bold text-slate-400">Preview</h3>

                {generatedImageUrl && (
                  <div className="rounded-xl overflow-hidden border border-slate-800 aspect-video relative group bg-slate-950">
                    <img src={generatedImageUrl} alt="AI output" className="w-full h-full object-cover" />
                    <button 
                      onClick={() => setGeneratedImageUrl('')}
                      className="absolute top-2 right-2 p-1.5 rounded-full bg-slate-950/80 hover:bg-slate-900 text-slate-400 hover:text-slate-200"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                )}

                <div className="flex-1 min-h-[250px] bg-slate-950 border border-slate-800 rounded-xl p-4 font-mono text-sm leading-relaxed overflow-y-auto whitespace-pre-wrap">
                  {generatedText || <span className="text-slate-600 italic">No text generated yet.</span>}
                </div>

                {generatedText && (
                  <button 
                    onClick={saveDraftPost}
                    className="bg-emerald-600 hover:bg-emerald-500 font-semibold rounded-lg py-2.5 transition"
                  >
                    Save draft as Post
                  </button>
                )}
              </div>
            </div>
          )}

          {currentPage === 'calendar' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
              {/* Form to Schedule */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 h-fit flex flex-col gap-4">
                <h3 className="text-lg font-bold">Schedule Content</h3>
                <form onSubmit={handleSchedulePost} className="flex flex-col gap-4">
                  <div>
                    <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Select Draft</label>
                    <select 
                      value={selectedPostId} 
                      onChange={(e) => setSelectedPostId(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none"
                    >
                      <option value="">-- Choose Post --</option>
                      {posts.map(p => (
                        <option key={p.id} value={p.id}>{p.title}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Publish Time</label>
                    <input 
                      type="datetime-local" 
                      required 
                      value={scheduleDate}
                      onChange={(e) => setScheduleDate(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Repeat Cadence</label>
                    <select 
                      value={repeatCadence} 
                      onChange={(e) => setRepeatCadence(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none"
                    >
                      <option value="none">One-off Post</option>
                      <option value="daily">Daily Cadence</option>
                      <option value="weekly">Weekly Cadence</option>
                      <option value="monthly">Monthly Cadence</option>
                    </select>
                  </div>
                  <button 
                    type="submit" 
                    className="bg-indigo-600 hover:bg-indigo-500 font-semibold py-2 rounded-lg transition"
                  >
                    Confirm Schedule
                  </button>
                </form>
              </div>

              {/* Dynamic Calendar Grid */}
              <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-lg font-bold">
                    {currentMonth.toLocaleString('default', { month: 'long', year: 'numeric' })}
                  </h3>
                  <div className="flex gap-2">
                    <button 
                      onClick={() => {
                        const prev = new Date(currentMonth);
                        prev.setMonth(prev.getMonth() - 1);
                        setCurrentMonth(prev);
                      }}
                      className="p-2 rounded bg-slate-800 hover:bg-slate-700 transition text-xs font-semibold text-slate-200"
                    >
                      Prev Month
                    </button>
                    <button 
                      onClick={() => {
                        const next = new Date(currentMonth);
                        next.setMonth(next.getMonth() + 1);
                        setCurrentMonth(next);
                      }}
                      className="p-2 rounded bg-slate-800 hover:bg-slate-700 transition text-xs font-semibold text-slate-200"
                    >
                      Next Month
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-7 gap-2 text-center text-xs font-semibold text-slate-500 uppercase mb-2">
                  <div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div><div>Sun</div>
                </div>

                <div className="grid grid-cols-7 gap-2">
                  {(() => {
                    const year = currentMonth.getFullYear();
                    const month = currentMonth.getMonth();
                    const firstDay = new Date(year, month, 1);
                    const offset = (firstDay.getDay() + 6) % 7;
                    const totalDays = new Date(year, month + 1, 0).getDate();
                    
                    const cells = [];
                    for (let i = 0; i < offset; i++) {
                      cells.push({ dayNum: null, dateStr: null });
                    }
                    for (let d = 1; d <= totalDays; d++) {
                      const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
                      cells.push({ dayNum: d, dateStr });
                    }
                    
                    return cells.map((cell, i) => {
                      if (!cell.dayNum) {
                        return <div key={`empty-${i}`} className="min-h-[90px] bg-slate-950/20 rounded-lg p-2 border border-transparent"></div>;
                      }
                      
                      const dayEvents = calendarPosts.filter(p => {
                        const pubDate = new Date(p.publish_at);
                        const localStr = `${pubDate.getFullYear()}-${String(pubDate.getMonth() + 1).padStart(2, '0')}-${String(pubDate.getDate()).padStart(2, '0')}`;
                        return localStr === cell.dateStr;
                      });
                      
                      return (
                        <div key={`day-${cell.dayNum}`} className="min-h-[90px] bg-slate-950 border border-slate-800 rounded-lg p-2 flex flex-col justify-between hover:border-slate-700 transition">
                          <span className="text-xs font-bold text-slate-500">{cell.dayNum}</span>
                          <div className="flex flex-col gap-1 overflow-y-auto max-h-[60px] scrollbar-none">
                            {dayEvents.map(evt => {
                              const matchingPost = posts.find(p => p.id === evt.content_id);
                              return (
                                <button
                                  key={evt.id}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelectedCalendarEvent(evt);
                                  }}
                                  className="w-full text-left bg-indigo-950/80 border border-indigo-900 text-[10px] text-indigo-300 p-1 rounded truncate hover:bg-indigo-900 transition"
                                >
                                  {matchingPost?.title || "Scheduled Post"}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>
            </div>
          )}

          {currentPage === 'marketplace' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
              <div className="flex flex-col gap-8">
                {/* Sell form */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col gap-4">
                  <h3 className="text-lg font-bold">Sell Credits</h3>
                  <form onSubmit={handleListCredits} className="flex flex-col gap-4">
                    <div>
                      <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Amount to Sell</label>
                      <input 
                        type="number" 
                        required 
                        min={1} 
                        value={sellCreditsAmount}
                        onChange={(e) => setSellCreditsAmount(parseInt(e.target.value))}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Price (in cents)</label>
                      <input 
                        type="number" 
                        required 
                        min={10} 
                        value={sellCreditsPrice}
                        onChange={(e) => setSellCreditsPrice(parseInt(e.target.value))}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none"
                      />
                    </div>
                    <button 
                      type="submit" 
                      className="bg-indigo-600 hover:bg-indigo-500 font-semibold py-2 rounded-lg transition"
                    >
                      Post Listing
                    </button>
                  </form>
                </div>
              </div>

              {/* listings and credit packs */}
              <div className="lg:col-span-2 flex flex-col gap-8">
                {/* Buy Credit Packs directly with Stripe */}
                {currentAccount?.role === 'owner' && (
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                    <h3 className="text-lg font-bold mb-4 text-indigo-400">Purchase Additional Credits (Stripe Sandbox)</h3>
                    <div className="grid grid-cols-3 gap-4">
                      <div className="bg-slate-950 p-4 rounded-xl border border-slate-850 flex flex-col justify-between items-center gap-3">
                        <span className="font-bold text-slate-200">100 Credits</span>
                        <span className="text-emerald-400 font-bold">$5.00</span>
                        <button
                          onClick={() => handleUpgradeSubscription('credits_100')}
                          className="w-full bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold py-2 rounded-lg transition"
                        >
                          Buy Pack
                        </button>
                      </div>
                      <div className="bg-slate-950 p-4 rounded-xl border border-slate-850 flex flex-col justify-between items-center gap-3">
                        <span className="font-bold text-slate-200">500 Credits</span>
                        <span className="text-emerald-400 font-bold">$20.00</span>
                        <button
                          onClick={() => handleUpgradeSubscription('credits_500')}
                          className="w-full bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold py-2 rounded-lg transition"
                        >
                          Buy Pack
                        </button>
                      </div>
                      <div className="bg-slate-950 p-4 rounded-xl border border-slate-850 flex flex-col justify-between items-center gap-3">
                        <span className="font-bold text-slate-200">1000 Credits</span>
                        <span className="text-emerald-400 font-bold">$35.00</span>
                        <button
                          onClick={() => handleUpgradeSubscription('credits_1000')}
                          className="w-full bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold py-2 rounded-lg transition"
                        >
                          Buy Pack
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                  <h3 className="text-lg font-bold mb-4">Peer-to-Peer Marketplace listings</h3>
                  <div className="flex flex-col gap-3">
                    {marketListings.map((list) => (
                      <div key={list.id} className="bg-slate-950 border border-slate-800 p-4 rounded-xl flex items-center justify-between">
                        <div>
                          <p className="font-semibold">{list.amount} Credits</p>
                          <p className="text-xs text-slate-500">Seller: {list.seller_account_id}</p>
                        </div>
                        <div className="flex items-center gap-4">
                          <span className="text-emerald-400 font-extrabold">${(list.price / 100).toFixed(2)}</span>
                          {list.seller_account_id !== currentAccount.account_id ? (
                            <button 
                              onClick={() => handleBuyCredits(list.id)}
                              className="bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold px-4 py-2 rounded-lg transition"
                            >
                              Buy
                            </button>
                          ) : (
                            <span className="text-xs text-slate-500 italic">Your Listing</span>
                          )}
                        </div>
                      </div>
                    ))}
                    {marketListings.length === 0 && (
                      <p className="text-slate-500 italic text-sm">No listings currently active on the market.</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {currentPage === 'billing' && (
            <div className="flex flex-col gap-8">
              {/* Pricing Cards */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Free */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 flex flex-col justify-between">
                  <div>
                    <h4 className="font-bold text-xl mb-2">Free Plan</h4>
                    <p className="text-slate-400 text-sm mb-6">100 monthly credits. Standard text completions.</p>
                    <span className="text-3xl font-extrabold">$0</span><span className="text-slate-500 text-sm">/mo</span>
                  </div>
                  <button 
                    disabled 
                    className="mt-8 w-full bg-slate-800 text-slate-500 font-semibold py-2.5 rounded-lg border border-slate-700"
                  >
                    Current Tier
                  </button>
                </div>
                {/* Pro */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 flex flex-col justify-between border-indigo-600/50 shadow-lg shadow-indigo-600/5">
                  <div>
                    <h4 className="font-bold text-xl mb-2 text-indigo-400">Pro Plan</h4>
                    <p className="text-slate-400 text-sm mb-6">1,000 monthly credits. Fast & High Quality completions.</p>
                    <span className="text-3xl font-extrabold">$19</span><span className="text-slate-500 text-sm">/mo</span>
                  </div>
                  <button 
                    onClick={() => handleUpgradeSubscription('pro')}
                    className="mt-8 w-full bg-indigo-600 hover:bg-indigo-500 font-semibold py-2.5 rounded-lg transition"
                  >
                    Upgrade Plan
                  </button>
                </div>
                {/* Team */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 flex flex-col justify-between">
                  <div>
                    <h4 className="font-bold text-xl mb-2 text-purple-400">Team Plan</h4>
                    <p className="text-slate-400 text-sm mb-6">5,000 monthly credits. Full multi-seat workspace controls.</p>
                    <span className="text-3xl font-extrabold">$49</span><span className="text-slate-500 text-sm">/mo</span>
                  </div>
                  <button 
                    onClick={() => handleUpgradeSubscription('team')}
                    className="mt-8 w-full bg-indigo-600 hover:bg-indigo-500 font-semibold py-2.5 rounded-lg transition"
                  >
                    Upgrade Plan
                  </button>
                </div>
              </div>

              {/* Billing Invoice history */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <h3 className="text-lg font-bold mb-4">Payment Invoices</h3>
                <div className="flex flex-col gap-2">
                  {invoices.map((inv) => (
                    <div key={inv.id} className="bg-slate-950 p-4 rounded-xl flex items-center justify-between border border-slate-800">
                      <div>
                        <p className="text-sm font-semibold">{inv.stripe_invoice_id}</p>
                        <p className="text-xs text-slate-500">{new Date(inv.created_at).toLocaleDateString()}</p>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="text-emerald-400 font-extrabold">${(inv.amount / 100).toFixed(2)}</span>
                        <span className="text-xs uppercase bg-emerald-950 text-emerald-400 border border-emerald-900 px-2 py-0.5 rounded font-bold">
                          {inv.status}
                        </span>
                      </div>
                    </div>
                  ))}
                  {invoices.length === 0 && (
                    <p className="text-slate-500 italic text-sm">No payment history found.</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {currentPage === 'team' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
              {/* Invite member */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 h-fit flex flex-col gap-4">
                <h3 className="text-lg font-bold">Invite Member</h3>
                <form onSubmit={handleInviteMember} className="flex flex-col gap-4">
                  <div>
                    <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Email Address</label>
                    <input 
                      type="email" 
                      required 
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Workspace Role</label>
                    <select 
                      value={inviteRole} 
                      onChange={(e) => setInviteRole(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none"
                    >
                      <option value="member">Workspace Member</option>
                      <option value="admin">Workspace Admin</option>
                    </select>
                  </div>
                  <button 
                    type="submit" 
                    className="bg-indigo-600 hover:bg-indigo-500 font-semibold py-2 rounded-lg transition"
                  >
                    Send Invitation
                  </button>
                </form>
              </div>

              {/* Members listing */}
              <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <h3 className="text-lg font-bold mb-4">Workspace Members</h3>
                <div className="flex flex-col gap-3">
                  {members.map((member) => (
                    <div key={member.id} className="bg-slate-950 p-4 rounded-xl flex items-center justify-between border border-slate-800">
                      <div>
                        <p className="font-semibold text-sm">User ID: {member.user_id}</p>
                        <p className="text-xs text-slate-500">Joined: {new Date(member.created_at).toLocaleDateString()}</p>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-bold uppercase bg-indigo-950 border border-indigo-900 text-indigo-300 px-2 py-0.5 rounded">
                          {member.role}
                        </span>
                        {['owner', 'admin'].includes(currentAccount?.role) && member.role !== 'owner' && (
                          <button
                            onClick={() => handleRemoveMember(member.id)}
                            className="p-1.5 rounded-lg bg-red-950/20 text-red-400 hover:bg-red-950/55 hover:text-red-300 transition"
                            title="Remove Member"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {currentPage === 'admin-sessions' && (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
              <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                <Shield className="h-5 w-5 text-purple-400" />
                Active Sessions Manager (SuperAdmin Live state from Redis)
              </h3>
              <div className="flex flex-col gap-3">
                {activeSessions.map((session) => (
                  <div key={session.jti} className="bg-slate-950 p-4 rounded-xl flex items-center justify-between border border-slate-800">
                    <div>
                      <p className="font-mono text-xs text-purple-300">JTI: {session.jti}</p>
                      <p className="text-xs text-slate-500">User ID: {session.user_id}</p>
                    </div>
                    <button 
                      onClick={() => handleRevokeSession(session.jti)}
                      className="bg-red-950/40 hover:bg-red-900/60 border border-red-900 text-red-300 text-xs px-3 py-1.5 rounded-lg transition"
                    >
                      Revoke Session
                    </button>
                  </div>
                ))}
                {activeSessions.length === 0 && (
                  <p className="text-slate-500 italic text-sm">No active JWT sessions found in Redis.</p>
                )}
              </div>
            </div>
          )}

          {currentPage === 'admin-audit' && (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
              <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                <Clock className="h-5 w-5 text-purple-400" />
                Audit Trail Timeline
              </h3>
              <div className="flex items-center gap-2 mb-4">
                <Search className="h-4 w-4 text-slate-500" />
                <input 
                  type="text" 
                  value={auditSearch} 
                  onChange={(e) => setAuditSearch(e.target.value)}
                  placeholder="Filter events by routing key..."
                  className="bg-slate-950 border border-slate-800 text-sm rounded-lg px-3 py-1.5 outline-none w-64"
                />
              </div>
              <div className="flex flex-col gap-2 max-h-[500px] overflow-y-auto">
                {auditLogs
                  .filter(log => log.routing_key.includes(auditSearch))
                  .map((log) => (
                    <div key={log.id} className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs font-mono flex flex-col gap-2">
                      <div className="flex items-center justify-between border-b border-slate-900 pb-2">
                        <span className="text-purple-400 font-bold">{log.routing_key}</span>
                        <span className="text-slate-500">{log.created_at}</span>
                      </div>
                      <div className="text-slate-400 text-[10px] overflow-x-auto whitespace-pre-wrap">
                        {JSON.stringify(log.payload, null, 2)}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {currentPage === 'create-team' && (
            <div className="max-w-md mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl">
              <h2 className="text-2xl font-bold mb-6 text-center">Create Team Workspace</h2>
              <form 
                onSubmit={async (e) => {
                  e.preventDefault();
                  const name = e.target.team_name.value;
                  if (!name) return;
                  try {
                    const res = await fetch(`${API_BASE}/accounts/create-team`, {
                      method: 'POST',
                      headers: getHeaders(),
                      body: JSON.stringify({ name })
                    });
                    if (res.ok) {
                      setInfo('Team workspace created successfully!');
                      await fetchUserAccounts();
                      setCurrentPage('dashboard');
                    }
                  } catch (err) {
                    setError('Failed to create team.');
                  }
                }}
                className="flex flex-col gap-4"
              >
                <div>
                  <label className="text-xs uppercase text-slate-500 font-semibold block mb-1">Team Name</label>
                  <input 
                    name="team_name"
                    type="text" 
                    required 
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 focus:border-indigo-500 outline-none"
                    placeholder="My Startup Workspace"
                  />
                </div>
                <button 
                  type="submit" 
                  className="mt-2 bg-indigo-600 hover:bg-indigo-500 font-semibold rounded-lg py-2.5 transition"
                >
                  Create Workspace
                </button>
              </form>
            </div>
          )}

          {currentPage === 'social-integrations' && (
            <div className="flex flex-col gap-8">
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <h3 className="text-lg font-bold mb-4">LinkedIn Integration</h3>
                
                {connections.length > 0 ? (
                  connections.map(conn => (
                    <div key={conn.id} className="bg-slate-950 p-6 border border-slate-800 rounded-xl flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></span>
                          <span className="font-semibold text-emerald-400 capitalize">Connected to {conn.platform}</span>
                        </div>
                        <p className="text-xs text-slate-500 font-mono">URN: {conn.person_urn}</p>
                        <p className="text-[10px] text-slate-600">Expires: {new Date(conn.expires_at).toLocaleDateString()}</p>
                      </div>
                      <button
                        onClick={handleSocialDisconnect}
                        className="bg-red-950/40 hover:bg-red-900/60 border border-red-900 text-red-300 text-xs px-4 py-2 rounded-lg transition"
                      >
                        Disconnect Account
                      </button>
                    </div>
                  ))
                ) : (
                  <div className="bg-slate-950 p-6 border border-slate-800 rounded-xl text-center flex flex-col items-center gap-4">
                    <p className="text-slate-400 text-sm">No active LinkedIn connection found for this workspace.</p>
                    <button
                      onClick={async () => {
                        const res = await fetch(`${API_BASE}/social/connect/linkedin`, { headers: getHeaders() });
                        const data = await res.json();
                        if (data.authorization_url) window.location.href = data.authorization_url;
                      }}
                      className="bg-indigo-600 hover:bg-indigo-500 font-semibold rounded-lg px-6 py-2.5 transition text-sm"
                    >
                      Connect LinkedIn Account
                    </button>
                  </div>
                )}
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <h3 className="text-lg font-bold mb-4">Publishing Log History</h3>
                <div className="flex flex-col gap-2">
                  {socialHistory.map((job) => (
                    <div key={job.id} className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs flex flex-col gap-2">
                      <div className="flex items-center justify-between border-b border-slate-900 pb-2">
                        <span className="text-slate-500">Job ID: {job.id}</span>
                        <span className="text-slate-500 font-mono">{new Date(job.created_at).toLocaleString()}</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-slate-400 font-mono truncate max-w-lg">Content ID: {job.content_id}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
                          job.status === 'published' || job.status === 'success'
                            ? 'bg-emerald-950/60 border-emerald-900 text-emerald-400'
                            : job.status === 'failed'
                            ? 'bg-red-950/60 border-red-900 text-red-400'
                            : 'bg-yellow-950/60 border-yellow-900 text-yellow-400'
                        }`}>
                          {job.status}
                        </span>
                      </div>
                      {job.error_reason && (
                        <p className="text-red-400 text-[10px] mt-1 italic">Reason: {job.error_reason}</p>
                      )}
                    </div>
                  ))}
                  {socialHistory.length === 0 && (
                    <p className="text-slate-500 italic text-sm text-center py-4">No publishing history recorded.</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {currentPage === 'admin-workspaces' && (
            <div className="flex flex-col gap-8">
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                  <Shield className="h-5 w-5 text-purple-400" />
                  Workspaces Directory (Platform Overview)
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-slate-400">
                    <thead className="text-xs uppercase bg-slate-950 text-slate-500 border-b border-slate-850">
                      <tr>
                        <th className="px-4 py-3">Workspace Name</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3">Plan</th>
                        <th className="px-4 py-3">Members</th>
                        <th className="px-4 py-3">Credits</th>
                        <th className="px-4 py-3">Tokens Used</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {adminWorkspaces.map(ws => (
                        <tr 
                          key={ws.account_id}
                          onClick={() => setSelectedWorkspaceDetails(ws)}
                          className="hover:bg-slate-800/40 cursor-pointer transition"
                        >
                          <td className="px-4 py-3.5 font-semibold text-slate-200">{ws.name}</td>
                          <td className="px-4 py-3.5 capitalize">{ws.type}</td>
                          <td className="px-4 py-3.5">
                            <span className="text-xs font-bold uppercase bg-indigo-950 border border-indigo-900 text-indigo-300 px-2 py-0.5 rounded">
                              {ws.plan_tier}
                            </span>
                          </td>
                          <td className="px-4 py-3.5">{ws.members_count}</td>
                          <td className="px-4 py-3.5 font-mono text-emerald-400">{ws.credit_balance}</td>
                          <td className="px-4 py-3.5 font-mono text-blue-400">{ws.total_tokens_used.toLocaleString()}</td>
                        </tr>
                      ))}
                      {adminWorkspaces.length === 0 && (
                        <tr>
                          <td colSpan={6} className="text-center py-6 italic text-slate-500">No workspaces found.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {selectedWorkspaceDetails && (
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col gap-4">
                  <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                    <h3 className="text-lg font-bold text-indigo-400">Workspace Detailed Metrics</h3>
                    <button 
                      onClick={() => setSelectedWorkspaceDetails(null)}
                      className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-850">
                      <span className="text-slate-500 block text-[10px] mb-1">WORKSPACE ID</span>
                      <span className="text-slate-300">{selectedWorkspaceDetails.account_id}</span>
                    </div>
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-850">
                      <span className="text-slate-500 block text-[10px] mb-1">PLAN TIER</span>
                      <span className="text-indigo-400 uppercase font-bold">{selectedWorkspaceDetails.plan_tier}</span>
                    </div>
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-850">
                      <span className="text-slate-500 block text-[10px] mb-1">CREDITS BALANCE</span>
                      <span className="text-emerald-400 font-bold">{selectedWorkspaceDetails.credit_balance}</span>
                    </div>
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-850">
                      <span className="text-slate-500 block text-[10px] mb-1">TOTAL TOKENS</span>
                      <span className="text-blue-400 font-bold">{selectedWorkspaceDetails.total_tokens_used}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {/* STRIPE SANDBOX SIMULATOR MODAL */}
      {mockCheckout && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 max-w-md w-full shadow-2xl flex flex-col gap-5 animate-in fade-in zoom-in duration-200">
            <div className="flex justify-between items-center border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold flex items-center gap-2 text-indigo-400">
                <Sparkles className="h-5 w-5" />
                Stripe Card Checkout (Sandbox)
              </h3>
              <button 
                onClick={() => {
                  setMockCheckout(null);
                  setMockCardNumber('');
                  setMockCardExpiry('');
                  setMockCardCvc('');
                  setMockCardName('');
                }}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            
            <div className="text-xs text-slate-400 flex flex-col gap-2">
              <p>You have entered the <strong>Stripe Test Sandbox Environment</strong>. Select the options below to simulate the transaction:</p>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-850 flex flex-col gap-1.5 font-semibold text-slate-300">
                <div className="flex justify-between">
                  <span>Product:</span>
                  <span className="text-slate-200 capitalize">
                    {mockCheckout.plan_tier.startsWith("credits_") 
                      ? `${mockCheckout.plan_tier.replace("credits_", "")} Credits Pack`
                      : `${mockCheckout.plan_tier} Plan Subscription`
                    }
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Amount due:</span>
                  <span className="text-emerald-400">
                    {mockCheckout.plan_tier.startsWith("credits_") 
                      ? (mockCheckout.plan_tier === "credits_100" ? "$5.00" : mockCheckout.plan_tier === "credits_500" ? "$20.00" : "$35.00")
                      : (mockCheckout.plan_tier === "pro" ? "$19.00/mo" : "$49.00/mo")
                    }
                  </span>
                </div>
              </div>
            </div>

            {/* Mock Card Form */}
            <form onSubmit={(e) => {
              e.preventDefault();
              const cleanCard = mockCardNumber.replace(/\s+/g, '');
              if (cleanCard.length < 16) {
                setError("Invalid card number. Must be 16 digits. (Try 4242 4242 4242 4242)");
                return;
              }
              if (!mockCardExpiry || !mockCardCvc) {
                setError("Please fill out all card details.");
                return;
              }
              // Clear inputs
              setMockCardNumber('');
              setMockCardExpiry('');
              setMockCardCvc('');
              setMockCardName('');
              handleAuthorizeSimulatedPayment();
            }} className="flex flex-col gap-4">
              <div>
                <label className="text-[10px] uppercase text-slate-500 font-semibold block mb-1">Cardholder Name</label>
                <input 
                  type="text" 
                  required
                  placeholder="Jane Doe"
                  value={mockCardName}
                  onChange={(e) => setMockCardName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none text-sm focus:border-indigo-500 transition"
                />
              </div>
              <div>
                <label className="text-[10px] uppercase text-slate-500 font-semibold block mb-1">Card Number</label>
                <input 
                  type="text" 
                  required
                  placeholder="4242 4242 4242 4242"
                  value={mockCardNumber}
                  onChange={(e) => {
                    const val = e.target.value.replace(/\D/g, '').slice(0, 16);
                    const formatted = val.replace(/(\d{4})(?=\d)/g, '$1 ');
                    setMockCardNumber(formatted);
                  }}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none text-sm font-mono focus:border-indigo-500 transition"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] uppercase text-slate-500 font-semibold block mb-1">Expiration (MM/YY)</label>
                  <input 
                    type="text" 
                    required
                    placeholder="12/28"
                    value={mockCardExpiry}
                    onChange={(e) => {
                      const val = e.target.value.replace(/\D/g, '').slice(0, 4);
                      const formatted = val.length > 2 ? `${val.slice(0, 2)}/${val.slice(2)}` : val;
                      setMockCardExpiry(formatted);
                    }}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none text-sm font-mono focus:border-indigo-500 transition"
                  />
                </div>
                <div>
                  <label className="text-[10px] uppercase text-slate-500 font-semibold block mb-1">CVC</label>
                  <input 
                    type="password" 
                    required
                    placeholder="123"
                    value={mockCardCvc}
                    onChange={(e) => setMockCardCvc(e.target.value.replace(/\D/g, '').slice(0, 4))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none text-sm font-mono focus:border-indigo-500 transition"
                  />
                </div>
              </div>
              <div className="flex gap-4 mt-2">
                <button
                  type="submit"
                  className="flex-1 bg-indigo-600 hover:bg-indigo-500 font-semibold py-2.5 rounded-xl transition text-sm"
                >
                  Pay & Authorize
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMockCheckout(null);
                    setMockCardNumber('');
                    setMockCardExpiry('');
                    setMockCardCvc('');
                    setMockCardName('');
                    setError("Stripe Checkout was cancelled.");
                  }}
                  className="flex-1 bg-slate-800 hover:bg-slate-750 font-semibold py-2.5 rounded-xl border border-slate-700 transition text-sm hover:text-slate-200"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* PAYMENT CELEBRATION / SUCCESS MODAL */}
      {successModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 max-w-sm w-full shadow-2xl flex flex-col items-center gap-6 text-center animate-in fade-in zoom-in duration-200">
            <div className="w-16 h-16 rounded-full bg-emerald-950 border border-emerald-500 flex items-center justify-center text-emerald-400 text-3xl">
              ✓
            </div>
            <div>
              <h3 className="text-xl font-bold mb-2">Payment Complete!</h3>
              <p className="text-slate-400 text-xs">{successModal}</p>
            </div>
            <div className="flex gap-2 w-full">
              <button
                onClick={() => {
                  setSuccessModal('');
                  fetchCreditsBalance();
                }}
                className="flex-1 bg-emerald-600 hover:bg-emerald-500 font-semibold py-2.5 rounded-xl transition text-xs"
              >
                Close & View Balance
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CONFIRMATION DIALOG MODAL */}
      {confirmAction && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 max-w-sm w-full shadow-2xl flex flex-col items-center gap-6 text-center animate-in fade-in zoom-in duration-200">
            <div className="w-12 h-12 rounded-full bg-red-950/60 border border-red-500 flex items-center justify-center text-red-400 text-xl font-bold">
              !
            </div>
            <div>
              <h3 className="text-lg font-bold mb-2">Confirm Action</h3>
              <p className="text-slate-400 text-xs">{confirmAction.message}</p>
            </div>
            <div className="flex gap-4 w-full">
              <button
                onClick={confirmAction.onConfirm}
                className="flex-1 bg-red-600 hover:bg-red-500 font-semibold py-2.5 rounded-xl transition text-xs text-white"
              >
                Confirm
              </button>
              <button
                onClick={() => setConfirmAction(null)}
                className="flex-1 bg-slate-800 hover:bg-slate-700 font-semibold py-2.5 rounded-xl border border-slate-700 transition text-xs text-slate-300"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CALENDAR EVENT DETAIL MODAL */}
      {selectedCalendarEvent && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          {(() => {
            const matchingPost = posts.find(p => p.id === selectedCalendarEvent.content_id);
            return (
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-6 animate-in fade-in zoom-in duration-200">
                <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                  <h3 className="text-lg font-bold text-indigo-400">Scheduled Item Details</h3>
                  <button 
                    onClick={() => {
                      setSelectedCalendarEvent(null);
                      setRescheduleDate('');
                    }}
                    className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                
                <div className="flex flex-col gap-3 text-xs">
                  <div>
                    <span className="text-slate-500 block uppercase font-bold text-[10px] mb-1">Post Title</span>
                    <p className="text-slate-200 font-semibold text-sm">{matchingPost?.title || "Untitled Post"}</p>
                  </div>
                  <div>
                    <span className="text-slate-500 block uppercase font-bold text-[10px] mb-1">Post Body Preview</span>
                    <p className="text-slate-400 italic line-clamp-3 bg-slate-950 p-2.5 rounded-lg border border-slate-850">{matchingPost?.body || "No body content"}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-slate-500 block uppercase font-bold text-[10px] mb-1">Publish Time</span>
                      <p className="text-slate-300 font-mono font-semibold">{new Date(selectedCalendarEvent.publish_at).toLocaleString()}</p>
                    </div>
                    <div>
                      <span className="text-slate-500 block uppercase font-bold text-[10px] mb-1">Cadence</span>
                      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-indigo-950 text-indigo-400 border border-indigo-900">
                        {selectedCalendarEvent.repeat_cadence || "none"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Reschedule Form */}
                <form onSubmit={handleReschedulePost} className="border-t border-slate-800 pt-4 flex flex-col gap-3">
                  <span className="text-slate-500 block uppercase font-bold text-[10px]">Reschedule Publication</span>
                  <div className="flex gap-2">
                    <input
                      type="datetime-local"
                      required
                      value={rescheduleDate}
                      onChange={(e) => setRescheduleDate(e.target.value)}
                      className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 outline-none text-xs text-slate-200"
                    />
                    <button
                      type="submit"
                      className="bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold px-4 py-2 rounded-lg transition"
                    >
                      Reschedule
                    </button>
                  </div>
                </form>

                <div className="border-t border-slate-800 pt-4 flex justify-end gap-2">
                  <button
                    onClick={() => handleCancelSchedule(selectedCalendarEvent.id)}
                    className="bg-red-950/40 hover:bg-red-900/60 border border-red-900 text-red-300 text-xs px-4 py-2 rounded-lg transition font-semibold"
                  >
                    Cancel Scheduled Post
                  </button>
                </div>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
