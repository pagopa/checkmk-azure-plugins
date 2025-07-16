# CheckMK MKP packages builder

Building CheckMK packages
([MKPs](https://docs.checkmk.com/latest/en/mkps.html)) requires the
`mkp` executable, that is bundled in a CheckMK instance.  This image
provides the `mkp` executable as a container without the need of a
full running CheckMK.

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
