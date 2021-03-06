from salesforce_bulk import SalesforceBulk

from cumulusci.tasks.salesforce import BaseSalesforceTask
from cumulusci.salesforce_api.utils import get_simple_salesforce_connection


class BaseSalesforceApiTask(BaseSalesforceTask):
    name = "BaseSalesforceApiTask"
    api_version = None

    def _init_task(self):
        self.sf = self._init_api()
        self.bulk = self._init_bulk()
        self.tooling = self._init_api("tooling/")
        self._init_class()

    def _init_api(self, base_url=None):
        rv = get_simple_salesforce_connection(
            self.project_config, self.org_config, api_version=self.api_version
        )
        if base_url is not None:
            rv.base_url += base_url

        return rv

    def _init_bulk(self):
        return SalesforceBulk(
            host=self.org_config.instance_url.replace("https://", "").rstrip("/"),
            sessionId=self.org_config.access_token,
        )

    def _init_class(self):
        pass

    def _get_tooling_object(self, obj_name):
        obj = getattr(self.tooling, obj_name)
        obj.base_url = obj.base_url.replace("/sobjects/", "/tooling/sobjects/")
        return obj
