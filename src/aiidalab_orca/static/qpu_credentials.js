export function render({ model, el }) {
  const form = document.createElement("form");
  const field = (label, type = "text") => {
    const row = document.createElement("label");
    row.style.cssText = "display:block;margin:8px 0";
    row.append(document.createTextNode(label + " "));
    const input = document.createElement("input");
    input.type = type;
    input.autocomplete = "off";
    input.style.maxWidth = "100%";
    row.append(input); form.append(row);
    return input;
  };
  const name = field("Account name");
  const instance = field("Instance CRN");
  instance.style.width = "650px";
  const key = field("IBM Cloud API key", "password");
  key.autocomplete = "new-password";
  key.spellcheck = false;
  const replace = field("Replace this saved account", "checkbox");
  const save = document.createElement("button");
  save.type = "submit"; save.textContent = "Save and select account";
  form.append(save);
  const selected = document.createElement("select");
  selected.setAttribute("aria-label", "Saved IBM account");
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const button = (label, action) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label;
    b.onclick = () => model.send({ action });
    return b;
  };
  const update = () => {
    selected.replaceChildren();
    const blank = new Option("Select a saved account", ""); selected.append(blank);
    for (const account of model.get("accounts")) selected.append(new Option(account.name, account.name));
    selected.value = model.get("selected");
    status.textContent = model.get("status");
  };
  selected.onchange = () => model.send({ action: "select", name: selected.value });
  const submit = event => {
    event.preventDefault();
    // No secret is assigned to model attributes, DOM attributes or notebook state.
    model.send({ action: "save", name: name.value.trim(), instance: instance.value.trim(),
      token: key.value, replace: replace.checked });
    key.value = "";
  };
  form.addEventListener("submit", submit);
  el.append(form, selected, button("Check connection (no QPU job)", "check"),
    button("Refresh accounts", "refresh"), status);
  model.on("change:accounts change:selected change:status", update);
  update();
  return () => {
    key.value = "";
    form.removeEventListener("submit", submit);
    model.off("change:accounts change:selected change:status", update);
    el.replaceChildren();
  };
}
