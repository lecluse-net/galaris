"""Every declared setting has an explicit, independently delegable policy."""

import json

import pytest

from core.params import declared_rows
from core.params.access import PARAMETER_DOMAINS, parameter_privileges, generate_parameter_access_file
from core.authorize import PrivilegeService
from .test_guard_policy_parameters import actor


def test_all_declared_settings_and_generated_frontend_follow_the_same_policy(tmp_path):
    names = [str(row["name"]) for row in declared_rows()]
    catalogue = PrivilegeService().get_code_privileges()
    for name in names:
        assert set(parameter_privileges(name)) <= catalogue.keys(), name
    with pytest.raises(ValueError, match="no functional authorization"):
        parameter_privileges("synthetic.unclassified.setting")
    path = tmp_path / "access.ts"
    generate_parameter_access_file(names, path)
    policies = json.loads(path.read_text().split(" = ", 1)[1])
    assert policies == {name: list(parameter_privileges(name)) for name in sorted(names) if parameter_privileges(name)}
    assert policies["WEB_PUSH_DELAY_SECONDS"] == list(PARAMETER_DOMAINS["messaging"])
    assert "WEB_PUSH_VAPID_KEYS" not in policies


@pytest.mark.asyncio
@pytest.mark.parametrize("domain,pair", PARAMETER_DOMAINS.items())
async def test_each_settings_domain_reads_only_its_keys_and_only_its_writer_can_save(client, domain, pair):
    expected = {str(row["name"]) for row in declared_rows() if parameter_privileges(str(row["name"])) == pair}
    assert expected, domain
    for index, code in enumerate(pair):
        headers, _ = await actor([code])
        response = await client.get("/api/params", headers=headers)
        assert response.status_code == 200, (code, response.text)
        rows = {item["name"]: item for item in response.json()["params"]}
        assert set(rows) == expected, code
        key = sorted(expected)[0]
        saved = await client.put(f"/api/params/{key}", headers=headers, json={"value": rows[key]["value"]})
        assert saved.status_code == (200 if index and key != "goal.runtime.settings" else 403), (code, key, saved.text)
        foreign = next(str(row["name"]) for row in declared_rows() if parameter_privileges(str(row["name"])) not in ((), pair))
        assert (await client.put(f"/api/params/{foreign}", headers=headers, json={"value": None})).status_code == 403
        if index:
            for internal in ("AUTH_SECRET_KEY", "WEB_PUSH_VAPID_KEYS", "synthetic.unknown"):
                assert (await client.put(f"/api/params/{internal}", headers=headers, json={"value": None})).status_code == 404
