FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json ./
# The cache mount keeps npm's downloads between builds.
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
