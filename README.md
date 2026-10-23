

### Private Raspberry Pi deployment

GitHub deployments use Tailscale OIDC on `main`, an ephemeral `tag:pi-ci` runner,
and ordinary key-authenticated SSH to `100.109.96.69:22`. The Pi host key is pinned;
public SSH and disabled host-key verification are not used. Configure repository
variables `TS_OIDC_CLIENT_ID` and `TS_AUDIENCE` for a Tailscale federated identity
restricted to this repository's main branch and this deployment workflow.
Grant `tag:pi-ci` only TCP 22 on the Pi. Retain the existing deployment SSH key and
user/path secrets. Tailscale authentication does not replace SSH authentication.

The Tailscale action logs out its ephemeral runner in its automatic post-job
cleanup, including failed deployments. Tailscale then removes the machine; no
permanent runner enrollment is retained. Abrupt runner loss can delay automatic
removal until the ephemeral node expires.

Deployments share a Pi-side `flock` across repositories to prevent concurrent
Docker builds exhausting the Pi. Jobs wait up to 30 minutes for the lock.
