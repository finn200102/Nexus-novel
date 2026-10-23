import { textRevisionService } from "../../services/textRevisionService";
import type {ProviderInput} from "../../generated/api";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Banner, Button, Input, PageHeader, Select } from "../../components/ui";
import { readerToolsService, type ReaderProvider } from "../../services/readerToolsService";
import { getUserFacingError } from "../../services/apiClient";

import ProviderUsageLedger from "../../components/settings/ProviderUsageLedger";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";

function ProviderUsage({ row, refresh }: { row: ReaderProvider; refresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => { if (event.target === event.currentTarget) setOpen(event.currentTarget.open); }}><summary>Request accounting for {row.name}</summary>
    {open && <ProviderUsageLedger providerId={row.id} providerName={row.name} onChanged={refresh} />}
  </details>;
}
function Contents() {
  const [rows, setRows] = useState<ReaderProvider[]>([]);
  const [kind, setKind] = useState<ProviderInput["kind"]>("local");
  const [name, setName] = useState("");
  const [localDefaults,setLocalDefaults]=useState<{base_url:string;model:string}|null>(null);
  useEffect(()=>{void textRevisionService.defaults().then(setLocalDefaults).catch(()=>undefined);},[]);
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [inputPrice, setInputPrice] = useState("0");
  const [outputPrice, setOutputPrice] = useState("0");
  const [budget, setBudget] = useState("0");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [languages, setLanguages] = useState("");
  const [capabilities,setCapabilities]=useState<NonNullable<ProviderInput["capabilities"]>>(["translation","companion"]);
  const [imageModel,setImageModel]=useState("");
  const [imagePrice,setImagePrice]=useState("0");
  const [imageSizes,setImageSizes]=useState<NonNullable<ProviderInput["image_sizes"]>>(["1024x1024"]);
  const [imageQualities,setImageQualities]=useState<NonNullable<ProviderInput["image_qualities"]>>(["medium"]);
  const portraitSupported=kind==="local"||kind==="openai_compatible";
  const toggle=<T extends string,>(rows:T[],value:T)=>rows.includes(value)?rows.filter(item=>item!==value):[...rows,value];
  const refresh = async () => setRows(await readerToolsService.providers());
  useEffect(() => { void readerToolsService.providers().then(setRows).catch(() => setError("Couldn’t load providers.")); }, []);
  return <div>
    <PageHeader title="Companion & translation providers" description="Disabled until you configure a provider. Keys are encrypted on your Nexus server and never returned to the browser." />
    {error && <Banner tone="warning">{error}</Banner>}
    {rows.map((row) => <section key={row.id}><h2>{row.name}</h2><p>{row.model} · {row.enabled === false ? "Disabled" : "Enabled"} · budget ${row.budget_usd.toFixed(6)} · used ${row.used_usd.toFixed(6)} · reserved ${row.reserved_usd.toFixed(6)}</p>
      <p>{row.supported_languages?.length ? `Declared languages: ${row.supported_languages.join(", ")}` : "Language support has not been declared; try a paragraph preview first."}</p>
      <Button disabled={busy} onClick={() => { setEditing(row.id); setKind(row.kind as ProviderInput["kind"]); setName(row.name); setUrl(row.base_url); setModel(row.model); setKey(""); setInputPrice(String(row.input_price ?? 0)); setOutputPrice(String(row.output_price ?? 0)); setBudget(String(row.budget_usd)); setLanguages(row.supported_languages?.join(", ") ?? ""); setCapabilities(row.capabilities??["translation","companion"]);setImageModel(row.image_model??"");setImagePrice(String(row.image_price_usd??0));setImageSizes(row.image_sizes??["1024x1024"]);setImageQualities(row.image_qualities??["medium"]); }}>Edit provider</Button>
      <Button disabled={busy} onClick={() => { setBusy(true); setError(""); void readerToolsService.updateProvider(row.id, { enabled: row.enabled === false }).then(refresh).catch(err => setError(getUserFacingError(err, "Couldn’t change this provider."))).finally(() => setBusy(false)); }}>{row.enabled === false ? "Enable provider" : "Disable provider"}</Button>
      <ProviderUsage row={row} refresh={refresh} />
      {row.has_key && <Button disabled={busy} onClick={() => { setBusy(true); setError(""); void readerToolsService.updateProvider(row.id, { api_key: null }).then(refresh).catch(err => setError(getUserFacingError(err, "Couldn’t remove this key."))).finally(() => setBusy(false)); }}>Remove stored key</Button>}
    </section>)}
    <p>Disabling a provider also cancels its active translation jobs. Completed translations and original chapters are retained.</p>
    <form onSubmit={(event) => {
      event.preventDefault(); setBusy(true); setError("");
      const value = { name, base_url: url, model, ...(key ? { api_key: key } : {}),
        input_price: inputPrice, output_price: outputPrice, budget_usd: budget,
        capabilities,...(imageModel?{image_model:imageModel}:{}),...((editing==null||Number(imagePrice)!==Number(rows.find(row=>row.id===editing)?.image_price_usd??0))?{image_price_usd:imagePrice}:{}),image_sizes:imageSizes,image_qualities:imageQualities,
        supported_languages: languages.split(",").map(value => value.trim()).filter(Boolean) };
      void (editing == null ? readerToolsService.createProvider({ ...value, kind }) : readerToolsService.updateProvider(editing, value))
        .then(async () => { setKey(""); setEditing(null); await refresh(); })
        .catch((err) => setError(getUserFacingError(err, "Couldn’t save this provider."))).finally(() => setBusy(false));
    }}>
      {editing==null && kind==="local" && localDefaults?.base_url && <Button onClick={()=>{setUrl(localDefaults.base_url);setModel(localDefaults.model);setName("Local Qwen");}}>Use configured local model</Button>}
      <Input label="Provider name" value={name} required maxLength={120} onChange={(event) => setName(event.target.value)} />
      <Select label="Provider type" value={kind} disabled={editing != null} onChange={(event) => setKind(event.target.value as ProviderInput["kind"])} options={[
        { value: "local", label: "Local conversational model" }, { value: "local_translation", label: "Local translation model" },
        { value: "openai_compatible", label: "OpenAI-compatible API" }, { value: "openrouter", label: "OpenRouter" }, { value: "anthropic", label: "Anthropic · premium" },
      ]} />
      <Input label="API base URL" value={url} required type="url" onChange={(event) => setUrl(event.target.value)} hint="Include the API version path, for example https://api.anthropic.com/v1. Local endpoints must be configured by your administrator." />
      <Input label="Model" value={model} required maxLength={255} onChange={(event) => setModel(event.target.value)} hint="Choose the model you want, for example claude-opus-5-5." />
      <fieldset><legend>Allowed processing capabilities</legend>{([["translation","Translation"],["companion","Story questions"],["guide_text","Private guide cards and recaps"],["guide_portrait","Private character portraits"]] as const).map(([value,label])=><label key={value}><input type="checkbox" checked={capabilities.includes(value)} disabled={value==="guide_portrait"&&!portraitSupported&&!capabilities.includes(value)} onChange={()=>setCapabilities(toggle(capabilities,value))}/>{label}</label>)}</fieldset>
      {!portraitSupported&&<p>Portrait generation is unavailable for this provider type. Use an explicitly configured local or OpenAI-compatible image provider. Nexus never switches to a paid provider automatically.</p>}
      {capabilities.includes("guide_portrait")&&<fieldset><legend>Private image generation</legend><p>Story portrait permission and AO3 consent are separate from text processing. Image requests use the provider budget and the declared per-image ceiling.</p><Input label="Image model" required maxLength={255} value={imageModel} onChange={event=>setImageModel(event.target.value)} hint="Enter your provider’s supported image model. Nexus does not choose one automatically."/><Input label="Maximum image charge (USD per image)" type="number" min="0" max="100" step="0.000001" value={imagePrice} onChange={event=>setImagePrice(event.target.value)}/><fieldset><legend>Allowed image sizes</legend>{(["1024x1024","1536x1024","1024x1536"] as const).map(value=><label key={value}><input type="checkbox" checked={imageSizes.includes(value)} onChange={()=>setImageSizes(toggle(imageSizes,value))}/>{value}</label>)}</fieldset><fieldset><legend>Allowed image qualities</legend>{(["low","medium","high"] as const).map(value=><label key={value}><input type="checkbox" checked={imageQualities.includes(value)} onChange={()=>setImageQualities(toggle(imageQualities,value))}/>{value}</label>)}</fieldset></fieldset>}
      <Input label="Declared translation languages" value={languages} onChange={event => setLanguages(event.target.value)} hint="Optional language codes separated by commas, for example de, en, zh, ja. Quality still needs a paragraph preview." />
      <Input label={editing == null ? "API key" : "Replacement API key"} type="password" autoComplete="off" value={key} onChange={(event) => setKey(event.target.value)} hint={editing == null ? undefined : "Leave empty to keep the stored key."} />
      <Input label="Input price (USD per million tokens)" type="number" min="0" step="0.000001" value={inputPrice} onChange={(event) => setInputPrice(event.target.value)} />
      <Input label="Output price (USD per million tokens)" type="number" min="0" step="0.000001" value={outputPrice} onChange={(event) => setOutputPrice(event.target.value)} />
      <Input label="Total spending budget (USD)" type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} hint="Paid processing requires prices and a budget. A failed request may retain its reservation if the provider may have charged it." />
      <Button type="submit" variant="primary" loading={busy}>{editing == null ? "Save provider" : "Update provider"}</Button>
      {editing != null && <Button disabled={busy} onClick={() => { setEditing(null); setKey(""); setName(""); }}>Cancel editing</Button>}
    </form>
  </div>;
}

export default function Providers() {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={generation} />;
}
