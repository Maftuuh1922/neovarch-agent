# Neovarch relay, standalone (no npm dependencies).
#   docker build -t neovarch-relay relay/
#   docker run -d --restart unless-stopped -p 8787:8787 neovarch-relay
# Serve it through a TLS reverse proxy so phones use wss://.
FROM node:22-alpine
WORKDIR /app
COPY package.json ./
COPY src ./src
ENV PORT=8787 HOST=0.0.0.0 NODE_ENV=production
USER node
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8787/health || exit 1
CMD ["node", "src/node-server.js"]
