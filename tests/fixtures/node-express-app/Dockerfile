FROM node:20-slim AS runtime
WORKDIR /app
COPY package*.json /app/
RUN npm ci --omit=dev || npm install --omit=dev
COPY . /app
EXPOSE 3000
CMD ["node", "src/index.js"]
