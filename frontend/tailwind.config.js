/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f5f7ff',
          100: '#ebedff',
          200: '#dce0ff',
          300: '#c2c9ff',
          400: '#9fa8ff',
          500: '#757cff',
          600: '#5c5eff',
          700: '#4c49f5',
          800: '#3e3cc4',
          900: '#35339c',
          950: '#1f1e5c',
        }
      }
    },
  },
  plugins: [],
}
