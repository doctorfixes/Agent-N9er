FROM node:22-alpine
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build && chown -R app:app .next
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://localhost:3000/ || exit 1
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
