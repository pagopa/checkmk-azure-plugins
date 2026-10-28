# This image is for building mkp packages, not for running a CheckMK instance.
# For details see: https://docs.checkmk.com/latest/en/mkps.html#_adding_an_mkp

FROM checkmk/check-mk-community:2.5.0p14@sha256:940b52a6983b61c64c217ebee81f62a41011850e2873ef8d8fa1c1af1bea40f5

# no problem about the admin password, this is just for building the mkp
RUN omd create --no-tmpfs -u 1000 -g 1000 --admin-password cmkadmin "$CMK_SITE_ID"

USER 1000

# these envs are taken from /omd/sites/cmk/.profile
ENV OMD_SITE=cmk
ENV OMD_ROOT=/omd/sites/cmk
ENV PATH=$OMD_ROOT/local/bin:$OMD_ROOT/bin:$OMD_ROOT/local/lib/perl5/bin:$PATH
ENV LD_LIBRARY_PATH=$OMD_ROOT/local/lib:$OMD_ROOT/lib
ENV PATH="$OMD_ROOT/lib/perl5/bin:$PATH"
ENV MODULEBUILDRC="$OMD_ROOT/.modulebuildrc"
ENV PERL_MM_OPT=INSTALL_BASE="$OMD_ROOT/local/lib/perl5/"
ENV REQUESTS_CA_BUNDLE=$OMD_ROOT/var/ssl/ca-certificates.crt
ENV SSL_CERT_FILE=$OMD_ROOT/var/ssl/ca-certificates.crt
ENV NAGIOS_PLUGIN_STATE_DIRECTORY="$OMD_ROOT/var/monitoring-plugins"
ENV MP_STATE_DIRECTORY=$NAGIOS_PLUGIN_STATE_DIRECTORY

ENTRYPOINT ["mkp"]
