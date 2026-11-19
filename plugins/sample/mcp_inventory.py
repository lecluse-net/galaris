"""Synthetic, read-only MCP Apps inventory demonstration."""

from typing import Literal

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

APP_URI = "ui://sample/inventory.html"
INVENTORY = (
    ("Cahier quadrillé", "Lyon", "Papeterie", 18),
    ("Crayon bleu", "Lille", "Papeterie", 52),
    ("Lampe de bureau", "Lyon", "Équipement", 7),
    ("Support écran", "Lille", "Équipement", 12),
)


def register_inventory(server: FastMCP) -> None:
    @server.tool(meta={"ui": {"resourceUri": APP_URI}}, annotations={"readOnlyHint": True})
    def sample_inventory(
        site: Literal["", "Lyon", "Lille"] = "",
        category: Literal["", "Papeterie", "Équipement"] = "",
    ) -> ToolResult:
        """Return a synthetic stock table, optionally filtered by site and category."""
        rows = [
            list(row) for row in INVENTORY
            if (not site or site == row[1]) and (not category or category == row[2])
        ]
        return ToolResult(
            content=f"Sample inventory, {len(rows)} matching rows.",
            structured_content={"table": {
                "title": "Stock de démonstration",
                "columns": ["Article", "Site", "Catégorie", "Quantité"],
                "rows": rows,
            }},
        )

    @server.resource(APP_URI, mime_type="text/html;profile=mcp-app")
    def inventory_form() -> str:
        """Present the optional filters for the sample inventory read tool."""
        return INVENTORY_FORM


INVENTORY_FORM = """<!doctype html>
<style>
  body { font: 14px system-ui, sans-serif; color-scheme: light dark; margin: 4px; }
  form { display: flex; flex-wrap: wrap; align-items: end; gap: 8px 12px; }
  label { display: grid; gap: 4px; }
  select, button { min-height: 32px; font: inherit; }
</style>
<form>
  <label><span id="siteLabel">Site</span>
    <select name="site"><option value="">Tous</option><option>Lyon</option><option>Lille</option></select>
  </label>
  <label><span id="categoryLabel">Catégorie</span>
    <select name="category"><option value="">Toutes</option><option>Papeterie</option><option>Équipement</option></select>
  </label>
  <button disabled>Appliquer</button>
</form>
<script>
const form = document.querySelector('form');
const button = form.querySelector('button');
const send = message => parent.postMessage({jsonrpc:'2.0', ...message}, '*');
let id = 1;
let pending = null;
function reportSize() {
  send({method:'ui/notifications/size-changed', params:{height:form.offsetHeight + 12}});
}
addEventListener('message', event => {
  if (event.source !== parent || event.data?.jsonrpc !== '2.0') return;
  const message = event.data;
  if (message.id === 1 && message.result) {
    const context = message.result.hostContext || {};
    const french = (context.locale || 'fr').startsWith('fr');
    document.documentElement.lang = french ? 'fr' : 'en';
    document.body.style.colorScheme = context.theme === 'dark' ? 'dark' : 'light';
    document.body.style.color = context.theme === 'dark' ? '#eeeeee' : '#292c30';
    if (!french) {
      document.querySelector('#categoryLabel').textContent = 'Category';
      form.elements.site.options[0].text = 'All';
      form.elements.category.options[0].text = 'All';
      button.textContent = 'Apply';
    }
    send({method:'ui/notifications/initialized'});
    button.disabled = false;
    reportSize();
  } else if (message.id === pending) {
    pending = null;
    button.disabled = false;
  }
});
form.addEventListener('submit', event => {
  event.preventDefault();
  if (button.disabled) return;
  button.disabled = true;
  pending = ++id;
  send({id:pending, method:'tools/call', params:{
    name:'sample_inventory', arguments:Object.fromEntries(new FormData(form))
  }});
});
new ResizeObserver(reportSize).observe(form);
send({id, method:'ui/initialize', params:{
  protocolVersion:'2026-01-26', appInfo:{name:'sample-inventory',version:'1.0.0'}, appCapabilities:{}
}});
</script>"""
