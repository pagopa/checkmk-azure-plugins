# CheckMK MKP packages builder

Building CheckMK packages
([MKPs](https://docs.checkmk.com/latest/en/mkps.html)) requires the
`mkp` executable, that is bundled in a CheckMK instance.  This image
provides the `mkp` executable as a container without the need of a
full running CheckMK.

The builder uses **Checkmk Community 2.5.0p14**, pinned to the same image digest
as the [local environment](../tests/compose/README.md). The base image is amd64;
Apple Silicon requires amd64 emulation.

## Publishing

The **Publish MKP builder** workflow rebuilds and publishes
`ghcr.io/pagopa/checkmk-mkp:latest` when this directory changes on `main`.
It can also be started manually.

Publish the updated builder before triggering a plugin release. The builder
and release workflows run independently: changing both in the same push does
not guarantee that the release will use the new builder.

## Usage

Run in the project root (or in another plugin to be packaged with similar folder structure).

```shell
mkdir -p .packages
export PLUGIN=<name-of-plugin-to-build>
docker run \
    --rm \
    -v $(pwd)/${PLUGIN}/${PLUGIN}:/opt/omd/sites/cmk/local/lib/python3/cmk_addons/plugins/${PLUGIN} \
    -v $(pwd)/${PLUGIN}/${PLUGIN}.manifest:/manifests/${PLUGIN}.manifest \
    -v $(pwd)/.packages/:/omd/sites/cmk/var/check_mk/packages_local/ \
    ghcr.io/pagopa/checkmk-mkp:latest\
    package /manifests/${PLUGIN}.manifest
```

You will now found your packaged MKP in the `.packages` folder.
