# Mission Control Access Points

This document describes how to access the Aegis Mission Control web UI from different network environments.

## Overview

Mission Control runs on two ports by default:
- **Port 8420**: Main Mission Control dashboard (web UI)
- **Port 8421**: Observer health endpoint (`/health`, `/health/ready`, `/health/live`)

Both bind to `0.0.0.0` by default (configurable via `aegis_config.yaml`).

---

## Access Methods

### 1. Local Development (Same Machine)
```bash
# Start the system
aegis start

# Access in browser
open http://localhost:8420
```

### 2. Remote Server via SSH Tunnel (Recommended)
**Most secure — no firewall changes needed**

```bash
# On your local machine, create tunnel to remote server
ssh -L 8420:localhost:8420 -L 8421:localhost:8421 user@your-server-ip

# Then access in your LOCAL browser:
# Mission Control:  http://localhost:8420
# Observer Health:  http://localhost:8421/health
```

**Example for Oracle Cloud:**
```bash
ssh -L 8420:localhost:8420 -L 8421:localhost:8421 ubuntu@207.211.172.66
```

**Windows (PowerShell/CMD):**
```cmd
ssh -L 8420:localhost:8420 -L 8421:localhost:8421 ubuntu@207.211.172.66
```

---

### 3. Direct Public IP Access (Requires Firewall Config)
**Use when SSH tunnel isn't practical**

#### Oracle Cloud Console Steps:
1. Go to **Networking** → **Virtual Cloud Networks** → Your VCN
2. Click **Security Lists** → **Default Security List** (or your custom one)
3. Click **Add Ingress Rules**:
   ```
   Source Type: CIDR
   Source CIDR: 0.0.0.0/0  (or your specific IP/32)
   IP Protocol: TCP
   Source Port Range: (leave blank)
   Destination Port Range: 8420,8421
   Description: Aegis Mission Control
   ```
4. Click **Add Ingress Rules**

#### On the Server (Ubuntu/Debian):
```bash
# Allow through UFW (if enabled)
sudo ufw allow 8420/tcp
sudo ufw allow 8421/tcp

# Or iptables
sudo iptables -A INPUT -p tcp --dport 8420 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 8421 -j ACCEPT
```

#### Access:
```
Mission Control:  http://207.211.172.66:8420
Observer Health:  http://207.211.172.66:8421/health
```

---

### 4. Tailscale Access (If Using Tailscale)
```bash
# On server (if not already running)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Get the Tailscale IP
tailscale ip -4
# e.g., 100.x.y.z

# Access from any Tailscale-connected device:
# http://100.x.y.z:8420
# http://your-hostname.tailnet.ts.net:8420  (if MagicDNS enabled)
```

---

### 5. Nginx Reverse Proxy (Production)
```nginx
# /etc/nginx/sites-available/aegis
server {
    listen 80;
    server_name aegis.yourdomain.com;

    location / {
        proxy_pass http://localhost:8420;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/aegis /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

### 6. From Within SSH Session (Text Browser)
```bash
# SSH into server
ssh ubuntu@207.211.172.66

# Install text browser
sudo apt-get install lynx

# Browse locally
lynx http://localhost:8420
```

---

## Configuration Reference

### aegis_config.yaml
```yaml
web:
  enabled: true
  host: "0.0.0.0"    # Bind address (0.0.0.0 = all interfaces)
  port: 8420         # Mission Control port
  cors_origins:
    - "http://localhost:8420"
    - "http://127.0.0.1:8420"
    # Add your domain for CORS:
    # - "https://aegis.yourdomain.com"

observer:
  health_port: 8421  # Observer health endpoint
```

---

## Quick Reference Card

| Method | Security | Setup Effort | Best For |
|--------|----------|--------------|----------|
| SSH Tunnel | ⭐⭐⭐⭐⭐ | Low | Daily development |
| Public IP + Firewall | ⭐⭐ | Medium | Team access, CI/CD |
| Tailscale | ⭐⭐⭐⭐ | Low (once set up) | Personal/team secure access |
| Nginx Proxy | ⭐⭐⭐ | Medium | Production with SSL |
| Text Browser (SSH) | ⭐⭐⭐⭐ | None | Quick checks |

---

## Troubleshooting

### Connection Refused
```bash
# Check if service is running
systemctl status aegis  # or check aegis start output

# Check listening ports
ss -tlnp | grep -E '8420|8421'

# Check firewall
sudo ufw status
# or
sudo iptables -L -n
```

### Tailscale Not Working
```bash
# Ensure service binds to Tailscale interface
# Check Tailscale IP
tailscale ip -4

# Verify connectivity from client
ping <tailscale-ip>
curl http://<tailscale-ip>:8420/health
```

### CORS Errors
Add your access domain to `aegis_config.yaml`:
```yaml
web:
  cors_origins:
    - "http://localhost:8420"
    - "http://your-tailscale-hostname:8420"
    - "https://aegis.yourdomain.com"
```

---

## Security Notes

1. **Never expose 8420/8421 directly to internet without authentication** — Mission Control has full system control
2. **Use SSH tunnel or Tailscale for daily access**
3. **If using public IP**: Restrict to your IP via security groups/firewall
4. **For production**: Use Nginx with TLS + authentication (Basic Auth, OAuth, etc.)
5. **Observer health (8421)** is read-only but reveals system internals — treat as sensitive

---

## Related Documentation
- [Environment Management](/docs/ENVIRONMENT_MANAGEMENT.md)
- [Secrets Management](/docs/SECRETS_MANAGEMENT.md)
- [Main README](/README.md)