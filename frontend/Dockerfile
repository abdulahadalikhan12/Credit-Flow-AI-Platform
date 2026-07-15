FROM node:20-alpine AS build

WORKDIR /app

COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps

COPY frontend ./
RUN npm run build

FROM nginx:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
