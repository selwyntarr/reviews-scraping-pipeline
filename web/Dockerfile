# Dev image: dependencies baked in, source bind-mounted by compose for hot reload.
FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
EXPOSE 3000
ENV WATCHPACK_POLLING=true CHOKIDAR_USEPOLLING=true
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
