"""Azure Monitor plugin GUI-based configuration.

In the CheckMK "special agent" framework, this file is responsible to
specify the params of the form in the GUI that is used to configured
the rules associated to this special agent.

During check execution, the elements of the form as submitted by the
user will be parsed into command line argument for the check,
libexec/agent_azuremonitor, by a dedicated source file,
server_side_calls/special_agent.py

"""

from cmk.rulesets.v1.form_specs import Dictionary
from cmk.rulesets.v1.form_specs import DictElement
from cmk.rulesets.v1.form_specs import MultilineText
from cmk.rulesets.v1.form_specs import Integer
from cmk.rulesets.v1.form_specs import String
from cmk.rulesets.v1.form_specs import DefaultValue
from cmk.rulesets.v1.form_specs import Password
from cmk.rulesets.v1.form_specs import migrate_to_password
from cmk.rulesets.v1.rule_specs import SpecialAgent
from cmk.rulesets.v1.rule_specs import Topic
from cmk.rulesets.v1.rule_specs import Help
from cmk.rulesets.v1.rule_specs import Title


def _formspec():
    return Dictionary(
        title=Title("Azure Monitor logs and metrics"),
        help_text=Help("This rule is used to query Azure Monitor "
                       "log analytics workspaces for metrics and logs."),
        elements={
            "tenant_id":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Azure Tenant ID"),
                    help_text=Help("ID of the Azure tenant"),
                ),
            ),
            "client_id":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Client ID"),
                    help_text=Help(
                        "Client ID of the Azure service principal"
                    ),
                ),
            ),
            "client_secret":
            DictElement(
                required=True,
                parameter_form=Password(
                    title=Title("Client secret"),
                    help_text=Help(
                        "Client secret of the Azure service principal"
                    ),
                    migrate=migrate_to_password,
                ),
            ),
            "resource_id":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Resource ID"),
                    help_text=Help("ID of the target Azure resource"),
                ),
            ),
            "query":
            DictElement(
                required=True,
                parameter_form=MultilineText(
                    title=Title("KQL query"),
                    help_text=Help(
                        "Query to execute to Azure Monitor in KQL "
                        "(Kusto Query Language) syntax"
                    ),
                    monospaced=True,
                ),
            ),
            "timedelta_seconds":
            DictElement(
                required=True,
                parameter_form=Integer(
                    title=Title("Time delta (seconds)"),
                    help_text=Help(
                        "Fetch logs not older than N seconds. "
                        "Match this to the refresh time of the check"
                    ),
                    prefill=DefaultValue(60),
                ),
            ),
            "count_crit":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title("Critical count threshold"),
                    help_text=Help(
                        "Threshold of log entries retrieved count "
                        "that will be considered as CRITICAL"
                    ),
                ),
            ),
            "count_warn":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title("Warning count threshold"),
                    help_text=Help(
                        "Threshold of log entries retrieved count "
                        "that will be considered as WARNING"
                    ),
                ),
            ),
            "proxy":
            DictElement(
                required=False,
                parameter_form=String(
                    title=Title("Proxy"),
                    help_text=Help(
                        "Proxy to the Azure Monitor requests, "
                        "in the form http(s)://my.proxy:8080 or, "
                        "with authentication, "
                        "http(s)://user:pwd@my.proxy:8080"
                    ),
                ),
            ),
        })


rule_spec_hellospecial = SpecialAgent(
    topic=Topic.CLOUD,
    name="azuremonitor",
    title=Title("Azure Monitor logs and metrics"),
    parameter_form=_formspec,
)
