"""Azure Function App plugin GUI-based configuration.

In the CheckMK "special agent" framework, this file is responsible to
specify the params of the form in the GUI that is used to configured
the rules associated to this special agent.

During check execution, the elements of the form as submitted by the
user will be parsed into command line argument for the check,
libexec/agent_azurefunctions, by a dedicated source file,
server_side_calls/special_agent.py

"""

from cmk.rulesets.v1.form_specs import Dictionary
from cmk.rulesets.v1.form_specs import DictElement
from cmk.rulesets.v1.form_specs import Integer
from cmk.rulesets.v1.form_specs import String
from cmk.rulesets.v1.form_specs import Password
from cmk.rulesets.v1.form_specs import migrate_to_password
from cmk.rulesets.v1.rule_specs import SpecialAgent
from cmk.rulesets.v1.rule_specs import Topic
from cmk.rulesets.v1.rule_specs import Help
from cmk.rulesets.v1.rule_specs import Title


def _formspec():
    return Dictionary(
        title=Title("Azure Functions checks"),
        help_text=Help("This rule is used to monitor Azure Functions "
                       "executions by querying App Insights."),
        elements={
            "tenant_id":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Azure Tenant ID"),
                    help_text=Help("ID of the Azure tenant"),
                ),
            ),
            "subscription_id":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Azure Subscription ID"),
                    help_text=Help("ID of the Azure subscription"),
                ),
            ),
            "resource_group":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Azure Resource Group"),
                    help_text=Help("Name of the Azure resource group"),
                ),
            ),
            "client_id":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Client ID"),
                    help_text=Help("Client ID of the Azure service principal"),
                ),
            ),
            "client_secret":
            DictElement(
                required=True,
                parameter_form=Password(
                    title=Title("Client secret"),
                    help_text=Help(
                        "Client secret of the Azure service principal"),
                    migrate=migrate_to_password,
                ),
            ),
            "appinsights_app_id":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("App ID of App Insights"),
                    help_text=Help("Get in Azure Portal on App Insights "
                                   "resource > Configure > API Access"),
                ),
            ),
            "timedelta_kql":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("KQL expression for time delta"),
                    help_text=Help(
                        "Time delta in the past to query in App Insights. "
                        "Expressed as KQL expression. Examples: 1d, 8.5h, 9m"),
                ),
            ),
            "proxy":
            DictElement(
                required=False,
                parameter_form=String(
                    title=Title("Proxy"),
                    help_text=Help("Proxy to HTTP(S) requests, "
                                   "in the form http(s)://my.proxy:8080 or, "
                                   "with authentication, "
                                   "http(s)://user:pwd@my.proxy:8080"),
                ),
            ),
        })


rule_spec_hellospecial = SpecialAgent(
    topic=Topic.CLOUD,
    name="azurefunctions",
    title=Title("Azure Functions invocations"),
    parameter_form=_formspec,
)
