FROM node:20-alpine

WORKDIR /app

# Install dependencies first for proper caching
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

# Expose Vite's default dev server port
EXPOSE 5173

# Run the dev server with host binding to expose to Docker network
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
