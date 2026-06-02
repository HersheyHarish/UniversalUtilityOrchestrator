FROM node:20-alpine

WORKDIR /app

# Install dependencies first for proper caching
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

RUN chmod +x docker-entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["./docker-entrypoint.sh"]
