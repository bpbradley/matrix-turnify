# matrix-turnify

Running this alongside a synapse server allows matrix clients to use cloudflares TURN servers for voice/video calling.
It is an alternative to self-hosting your own TURN servers. Data is still e2e encrypted by Matrix of course.

## Background

Matrix allows [setup of self hosted TURN servers](https://element-hq.github.io/synapse/latest/turn-howto.html)
via the [TURN server REST API](https://tools.ietf.org/html/draft-uberti-behave-turn-rest-00), but this is incompatible
with configuring synapse to use Cloudflare Calls which has its own means of generating short lived credentials.

Using a service like Cloudflare Calls was preferable to me, as I didn't want to open a large range of ports on my home network,
and TURN servers are notoriously unreliable when operated behind NAT. So it was either hosting something like [coturn](https://github.com/coturn/coturn)
on a remote VPS, or trying to get cloudflare calls to work.

The other advantage of Cloudflare Calls to me:

1. Robust security managed by cloudflare, so not being responsible for the security of my server
2. Scaling and geolocation is managed by cloudflare, so remote users will be connected to a nearby server rather than my single location
3. 1,000GB/month of data transfer is free. So it won't cost me anything for my modest use.

So I developed this as a way to get cloudflare calls working natively with matrix clients, even though the server doesn't technically support it.

## Requirements

1. Reverse Proxy supporting path redirects by regex on the same network (or at least reachable) by your synapse server
2. Valid API Key and Application Token for a TURN app with Cloudflare calls. Navigate to your cloudflare dashboard > Calls > Create > Turn App

matrix-turnify is basically a middle layer sitting between matrix clients and a synapse server.

1. A client sends a request matching `^.*/voip/turnServer$`.
2. A reverse proxy (e.g., Traefik) routes this request to matrix-turnify.
3. matrix-turnify forwards the request to synapse and waits for a response.
4. If synapse authenticates the request:
   - matrix-turnify generates session credentials using Cloudflare's TURN API.
   - The response is modified to include these credentials and returned to the client.
5. If the request fails authentication, the unmodified Synapse response is returned.

So, what this basically means is that this system relies on the ability for the server administrator to selectively route requests to `/voip/turnServer`
to turnify. Any reverse proxy should be able to do so, I am using Traefik and will provide examples.

## Setup with Docker Compose

Here is a sample for how you might set this up with traefik. This should be possible with any modern reverse proxy (NPM, Caddy, etc.).
Feel free to add additional middlewares etc, so long as the route is accessible. The service runs internally on port 4499

```yaml
services:
  matrix-turnify:
    image: ghcr.io/bpbradley/matrix-turnify:latest
    restart: always
    # This is the network your matrix server is accessible on. Not needed if on default network
    networks:
      - traefik
    environment:
      - SYNAPSE_BASE_URL=${SYNAPSE_BASE_URL}
      - CF_TURN_TOKEN_ID=${CF_TURN_TOKEN_ID}
      - CF_TURN_API_TOKEN=${CF_TURN_API_TOKEN}
      - TURN_CREDENTIAL_TTL_SECONDS=${TURN_CREDENTIAL_TTL_SECONDS:-86400}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    # Extra security options since this container needs very little permissions
    user: 1000:1000
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    # Configuration with traefik. Adjust according to your own setup. 
    labels:
      - traefik.enable=true
      - traefik.docker.network=traefik
      - traefik.http.routers.turnify.entrypoints=https
      - traefik.http.services.turnify.loadbalancer.server.port=4499
      - traefik.http.routers.turnify.rule=Host(`${SERVICE_HOSTNAME}`)&&
        PathRegexp(`^.*/voip/turnServer$`)
      - traefik.http.routers.turnify.priority=32 # Make sure that the synapse server has a LOWER number here, this app must take priority or traefik will route requests to synapse directly
      - traefik.http.routers.turnify.tls=true
networks:
  traefik:
    external: true
```

And a sample .env

```env
SYNAPSE_BASE_URL=http://synapse:8008 # If within the internal docker network, you should be able to access by container name via docker internal dns.
CF_TURN_TOKEN_ID=your_token_here
CF_TURN_API_TOKEN=your_api_key_here
TURN_CREDENTIAL_TTL_SECONDS=86400
SERVICE_HOSTNAME=matrix.example.com # MUST match your matrix server hostname
LOG_LEVEL=INFO
```

## Testing

You can easily test that it is working with curl.

 ```sh
 curl --header "Authorization: Bearer TOKEN_FROM_AUTHORIZED_MATRIX_USER" -X GET https://matrix.example.com/_matrix/client/v3/voip/turnServer
 ```

You should see a log of this request in matrix-turnify logs. You will also get an appropriate response. If the request was valid (i.e. you gave it your
actual auth token, which you can get from the about section of your matrix client) then it will return valid cloudflare call credentials in the form
expected by matrix clients. If it was a bad token, you will get an unauthorized response directly from your synapse server.

## Notes

This is just a hobby project I quickly threw together to solve a niche problem I had, it is not officially sponsored or known by the matrix / element / synapse
team. You are also of course subject to any and all conditions and terms of use specified by Cloudflare when using their service. I made a best effort to handle this
as securely as possible, but there may be bugs I am unaware of. Luckily, it is extremely simple code which should be pretty easy to audit yourself, and it works with
very few needed permissions.
