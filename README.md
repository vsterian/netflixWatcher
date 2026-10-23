

### Private Raspberry Pi deployment

GitHub deployments use Tailscale OIDC on `main`, an ephemeral `tag:pi-ci` runner,
and ordinary key-authenticated SSH to `100.109.96.69:22`. The Pi host key is pinned;
public SSH and disabled host-key verification are not used. Configure repository
variables `TS_OIDC_CLIENT_ID` and `TS_AUDIENCE` for a Tailscale federated identity
restricted to this repository's main branch and this deployment workflow.
Grant `tag:pi-ci` only TCP 22 on the Pi. Retain the existing deployment SSH key and
user/path secrets. Tailscale authentication does not replace SSH authentication.
