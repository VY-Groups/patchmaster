FROM node:22-alpine

WORKDIR /app

# Install dependencies first for caching
COPY package.json package-lock.json* ./
RUN npm install

# Copy source
COPY . .

# Expose Vite port
EXPOSE 3000

# Start Vite dev server with host access (script is "start"; vite.config.js sets port 3000)
CMD ["npm", "run", "start", "--", "--host"]
