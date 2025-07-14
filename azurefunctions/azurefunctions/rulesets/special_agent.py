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
            "functionapp_name":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Name of the Azure Function App"),
                    help_text=Help("Name of the Azure Function App resource"),
                ),
            ),
            "function_name":
            DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Name of the function in the Function App"),
                    help_text=Help("Name of the function deployed in the "
                                   "Function App, also known as \"operation\"."
                                   " Get it in the Function App Overview page "
                                   "under Functions tab"),
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
            "count_crit_upper":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title(
                        "Critical upper threshold for execution count"),
                    help_text=Help("Upper threshold for invocations count "
                                   "that should issue a critical alert"),
                ),
            ),
            "count_crit_lower":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title(
                        "Critical lower threshold for execution count"),
                    help_text=Help("Lower threshold for invocations count "
                                   "that should issue a critical alert"),
                ),
            ),
            "count_warn_upper":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title("Warning upper threshold for execution count"),
                    help_text=Help("Upper threshold for invocations count "
                                   "that should issue a warning alert"),
                ),
            ),
            "count_warn_lower":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title("Warning lower threshold for execution count"),
                    help_text=Help("Lower threshold for invocations count "
                                   "that should issue a warning alert"),
                ),
            ),
            "failure_crit_upper":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title(
                        "Critical upper threshold for execution failure"),
                    help_text=Help("Upper threshold for invocations failure "
                                   "that should issue a critical alert"),
                ),
            ),
            "failure_crit_lower":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title(
                        "Critical lower threshold for execution failure"),
                    help_text=Help("Lower threshold for invocations failure "
                                   "that should issue a critical alert"),
                ),
            ),
            "failure_warn_upper":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title(
                        "Warning upper threshold for execution failure"),
                    help_text=Help("Upper threshold for invocations failure "
                                   "that should issue a warning alert"),
                ),
            ),
            "failure_warn_lower":
            DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title(
                        "Warning lower threshold for execution failure"),
                    help_text=Help("Lower threshold for invocations failure "
                                   "that should issue a warning alert"),
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
