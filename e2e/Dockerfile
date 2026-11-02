FROM mcr.microsoft.com/playwright:v1.64.0-noble
WORKDIR /tests
COPY package*.json ./
RUN npm ci
COPY . .
CMD ["npm", "test"]
