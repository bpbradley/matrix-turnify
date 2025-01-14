from flask import Flask, request, Response, jsonify
import json
import requests
import os
import logging

app = Flask(__name__)

SYNAPSE_BASE_URL = os.getenv("SYNAPSE_BASE_URL", "http://synapse:8008")
CF_TURN_TOKEN_ID = os.getenv("CF_TURN_TOKEN_ID", "")
CF_TURN_API_TOKEN = os.getenv("CF_TURN_API_TOKEN", "")
TURN_CREDENTIAL_TTL_SECONDS = int(os.getenv("TURN_CREDENTIAL_TTL_SECONDS", 86400))

CLOUDFLARE_API_URL = "https://rtc.live.cloudflare.com/v1/turn/keys/{CF_TURN_TOKEN_ID}/credentials/generate"

# Ensure Flask logs are visible if running via gunicorn
if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        app.logger.warning(f"Invalid LOG_LEVEL '{log_level}' provided. Defaulting to 'INFO'.")
        log_level = "INFO"
    app.logger.setLevel(getattr(logging, log_level, logging.INFO))

@app.route('/<path:subpath>/voip/turnServer', methods=['GET'])
def proxy_request(subpath):
    # Get client IP just for logging.
    x_forwarded_for = request.headers.get('X-Forwarded-For', '')
    ip_addr = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.remote_addr

    target_url = f"{SYNAPSE_BASE_URL}/{subpath}/voip/turnServer"

    # Forward headers and query parameters as-is with the request
    headers = {key: value for key, value in request.headers if key.lower() != 'host'}
    params = request.args
    response = requests.get(
        url=target_url, headers=headers, params=params, stream=True
    )

    app.logger.info(f"{ip_addr} -- {response.status_code}")

    # ONLY if the unmodified response from the matrix server is successful (i.e. it authenticated properly)
    # can we continue with injecting cloudflare credentials
    if response.status_code == 200:
        try:
            # Call Cloudflare API to generate TURN credentials
            cloudflare_headers = {
                "Authorization": f"Bearer {CF_TURN_API_TOKEN}",
                "Content-Type": "application/json"
            }
            cloudflare_data = {"ttl": TURN_CREDENTIAL_TTL_SECONDS}

            cloudflare_response = requests.post(
                CLOUDFLARE_API_URL.format(CF_TURN_TOKEN_ID=CF_TURN_TOKEN_ID),
                headers=cloudflare_headers,
                json=cloudflare_data
            )
            cloudflare_response.raise_for_status()

            ice_servers = cloudflare_response.json().get("iceServers", {})
            turn_uris = ice_servers.get("urls", [])
            username = ice_servers.get("username", "")
            password = ice_servers.get("credential", "")

            modified_body = {
                "username": username,
                "password": password,
                "ttl": TURN_CREDENTIAL_TTL_SECONDS,
                "uris": turn_uris,
            }

            modified_body_json = json.dumps(modified_body)

            # Return the modified response with proper headers
            # And manually calculate content length because it was not being
            # handled correctly
            headers = {
                key: value for key, value in response.headers.items()
                if key.lower() not in ['content-length', 'transfer-encoding']
            }
            headers['Content-Length'] = str(len(modified_body_json))

            return Response(modified_body_json, status=200, headers=headers, content_type="application/json")
        except requests.exceptions.RequestException:
            app.logger.error(f"Failed to fetch TURN credentials from Cloudflare: {e}")

    # For non-200 responses or if Cloudflare API fails, return the original response.
    # basically, we were never here...
    def generate():
        for chunk in response.iter_content(chunk_size=8192):
            yield chunk

    return Response(
        generate(),
        status=response.status_code,
        headers={key: value for key, value in response.headers.items() if key.lower() != 'transfer-encoding'}
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4499)
