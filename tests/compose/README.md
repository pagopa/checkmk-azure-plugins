# Local Checkmk environment

Requires Docker and Docker Compose v2, available as `docker-compose` as used by
`up.sh`. The environment uses **Checkmk Community 2.5.0p14**, pinned by digest,
matching the target installation. The image is amd64; Apple Silicon requires
amd64 emulation.

Run the following commands from the repository root:

```shell
sh tests/compose/up.sh
```

Open **http://localhost:8080/cmk/** and log in as **cmkadmin** with the deliberately
fake password `localdev` defined in [compose.yaml](compose.yaml). These credentials
are for local development only and must never be used in production.
Change the port mapping in `compose.yaml` to use another local port. Only localhost
is published. This is a local HTTP development environment, not a production
deployment. Docker environment variables are visible to Docker administrators.

The startup script waits for Checkmk, deploys the three plugins from the
read-only source mount and builds their MKPs as version `0.1.0`. No Python
command runs on the host. Internet access is needed to download the container
image, not to install Python dependencies. Re-run the startup script after
changing plugin sources.

Site configuration and packages persist in a Docker volume:

```shell
docker-compose -f tests/compose/compose.yaml logs -f checkmk
docker-compose -f tests/compose/compose.yaml exec --user cmk checkmk bash -l
docker-compose -f tests/compose/compose.yaml down
```

`docker-compose down` preserves the site. The initial `CMK_PASSWORD` in Compose
only initializes a new site; change an existing password with
`cmk-passwd cmkadmin` as the site user. Configure Azure rules and hosts in the GUI
to perform live monitoring; no Azure credentials are baked into the image.
