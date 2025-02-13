from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import json
import requests
import os
import logging

app = Flask(__name__)
CORS(app)  # Allow CORS for all routes
SYNAPSE_BASE_URL = os.getenv("SYNAPSE_BASE_URL", "http://synapse:8008")
CF_TURN_TOKEN_ID = os.getenv("CF_TURN_TOKEN_ID", "")
CF_TURN_API_TOKEN = os.getenv("CF_TURN_API_TOKEN", "")
TURN_CREDENTIAL_TTL_SECONDS = int(os.getenv("TURN_CREDENTIAL_TTL_SECONDS", 86400))

CLOUDFLARE_API_URL = "https://rtc.live.cloudflare.com/v1/turn/keys/{CF_TURN_TOKEN_ID}/credentials/generate"

# Ensure Flask logs are visible if running via gunicorn
if __name__ != "__main__":  # Gunicorn environment
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)  # Inherit Gunicorn's log level

@app.before_request
def log_request():
    app.logger.debug(f"Received {request.method} request to {request.path} from {request.remote_addr}")
    
@app.route('/<path:subpath>/voip/turnServer', methods=['GET'])
def proxy_request(subpath):
    app.logger.debug(f"Handling {request.method} request for {request.path}")
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

    app.logger.info(f"{ip_addr} -- {response.status_code} -- {request.path}")

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
            headers = {
                key: value for key, value in response.headers.items()
                if key.lower() not in ['content-length', 'transfer-encoding']
            }
            headers['Content-Length'] = str(len(modified_body_json))

            return Response(modified_body_json, status=200, headers=headers, content_type="application/json")
        except requests.exceptions.RequestException as e:
            app.logger.error(f"{ip_addr} -- Failed to fetch TURN credentials from Cloudflare: {e}")

    # For non-200 responses or if Cloudflare API fails, return the original response.
    def generate():
        for chunk in response.iter_content(chunk_size=8192):
            yield chunk

    return Response(
        generate(),
        status=response.status_code,
        headers={key: value for key, value in response.headers.items() if key.lower() != 'transfer-encoding'}
    )

# Catch-all route for unexpected requests - Proxy to Synapse and log warning
# Ideally we should never be getting here, but try to minimize pain by proxying requests anyway
# If this route is reached, there is a reverse proxy issue.
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def catch_all(path):
    x_forwarded_for = request.headers.get('X-Forwarded-For', '')
    ip_addr = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.remote_addr

    # Log unexpected request
    app.logger.warning(f"{ip_addr} -- Unexpected request: {request.method} {request.path}, forwarding to Synapse.")

    target_url = f"{SYNAPSE_BASE_URL}/{path}"
    headers = {key: value for key, value in request.headers if key.lower() != 'host'}

    try:
        if request.method in ['POST', 'PUT', 'PATCH']:
            response = requests.request(request.method, target_url, headers=headers, json=request.get_json(), stream=True)
        else:
            response = requests.request(request.method, target_url, headers=headers, params=request.args, stream=True)

        # Return Synapse response unmodified
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk

        return Response(
            generate(),
            status=response.status_code,
            headers={key: value for key, value in response.headers.items() if key.lower() != 'transfer-encoding'}
        )
    
    except requests.exceptions.RequestException as e:
        app.logger.error(f"{ip_addr} -- Error forwarding request to Synapse: {e}")
        return jsonify({"error": "Failed to connect to Synapse"}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4499)
