&nbsp;

# Tresor — Container Access URLs (LAN)

| Service | Description | Port | URL |
| --- | --- | --- | --- |
| **Grafana** | Monitoring dashboard | `3000` | [http://192.168.1.100:3000](http://192.168.1.100:3000/) |
| **Prometheus** | Metrics collector | `9090` | [http://192.168.1.100:9090](http://192.168.1.100:9090/) |
| **FileBrowser** | File management UI | `8080` | [http://192.168.1.100:8080](http://192.168.1.100:8080/) |
| **Jellyfin** | Media server (LAN only) | `8096` | [http://192.168.1.100:8096](http://192.168.1.100:8096/) |
| **Uptime Kuma** | Public status page (runs on public_net, via CF Tunnel → Traefik; no host port published) | `—` | [https://mc-status.example.com](https://mc-status.example.com) |
| **Paper (Minecraft)** | Game server (not HTTP, WG-only) | `25565` | *`1.2.3.4:25565`* |

* * *

### Notes

- All listed services except Kuma and Paper are **LAN-only** (bound to `internal_net` or `lan_pub`).
    
- **Uptime Kuma** is accessible publicly via Cloudflare → Traefik
    
- **Traefik dashboard** is not exposed
    
- **PaperMC** is reachable only via WireGuard through the VPS proxy.
    

* * *

&nbsp;