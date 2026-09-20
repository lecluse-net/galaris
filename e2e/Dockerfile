FROM mcr.microsoft.com/playwright:v1.62.1-noble
WORKDIR /tests
COPY package*.json ./
RUN npm ci
COPY . .
CMD ["npm", "test"]
