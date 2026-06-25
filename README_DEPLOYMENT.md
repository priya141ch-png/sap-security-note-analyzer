# VM Deployment Guide

## Architecture

```
Developer Laptop
      │  git push
      ▼
GitHub Repository
      │  GitHub Actions / git pull
      ▼
Linux VM (Ubuntu 22.04)
      │  Docker Compose
      ▼
Streamlit App  ──►  http://<VM-IP>:8501
      ▲
Colleagues access from browser (no local install needed)
```

---

## 1. Prepare Ubuntu VM

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git docker.io docker-compose-plugin curl

sudo systemctl enable docker
sudo systemctl start docker

# Add your user to docker group (re-login after this)
sudo usermod -aG docker $USER
```

---

## 2. Clone and Configure

```bash
cd /opt
sudo git clone https://github.com/YOUR_ORG/sap-security-note-analyzer.git
sudo chown -R $USER:$USER sap-security-note-analyzer
cd sap-security-note-analyzer

cp .env.example .env
# Edit .env — set AUTH_ENABLED, AUTH_USERNAME, AUTH_PASSWORD_HASH
nano .env
```

---

## 3. Start the Application

```bash
docker compose up -d --build
```

Check it is running:

```bash
docker compose ps
docker logs -f sap-security-analyzer
```

Open in browser: `http://<VM-IP>:8501`

---

## 4. Nginx Reverse Proxy with Basic Auth (Recommended)

Install Nginx:

```bash
sudo apt install -y nginx apache2-utils
```

Create a password file:

```bash
sudo htpasswd -c /etc/nginx/.htpasswd sapuser
```

Create Nginx site config (`/etc/nginx/sites-available/sap-analyzer`):

```nginx
server {
    listen 80;
    server_name sap-security-analyzer.company.com;

    auth_basic "SAP Security Analyzer";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/sap-analyzer /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

For HTTPS, add a certificate with Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d sap-security-analyzer.company.com
```

---

## 5. Regular Update Workflow

On the developer laptop:

```bash
git add .
git commit -m "Improve SAP note parser"
git push
```

On the VM:

```bash
cd /opt/sap-security-note-analyzer
git pull
docker compose up -d --build
```

---

## 6. GitHub Actions Auto-Deploy (Optional)

Add `SSH_HOST`, `SSH_USER`, and `SSH_PRIVATE_KEY` as GitHub repository secrets.

The workflow at `.github/workflows/deploy.yml` will automatically deploy on every push to `main`.

---

## 7. Logs and Troubleshooting

```bash
# App logs
docker logs -f sap-security-analyzer

# Application log file
tail -f /opt/sap-security-note-analyzer/logs/app.log

# Restart
docker compose restart

# Full rebuild
docker compose down && docker compose up -d --build
```
