# Stream Relay

A small self-hosted replacement for Restream: each room's OBS sends one stream to this server, which forwards it to that room's YouTube, Facebook (RTMPS) and any other RTMP destination. Multiple rooms can be live at once, each with its own OBS key and destinations, all managed from a password-protected web page.

**Start here:** [SETUP-GUIDE.md](SETUP-GUIDE.md)

Quick install on a fresh Ubuntu server, as root:

```
git clone REPO_URL stream-relay && cd stream-relay && bash install.sh
```
