FROM node:22-alpine
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
