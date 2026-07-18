import { useEffect, useRef, useState } from "react";

import { api, type Session } from "./api";
import type {
  PackageContentUnitCode,
  PackagingType,
  ProductPrice,
  ProductUnitCode,
  ProjectConfiguration,
  ProjectProduct,
} from "./types";

interface Props {
  configuration: ProjectConfiguration;
  currency: string;
  session: Session;
  disabled: boolean;
  onPendingChange: (pending: boolean) => void;
  onSaved: (rowVersion: number) => void;
}

const packagingTypes: PackagingType[] = ["sack", "pail", "drum", "tote", "bulk", "case", "each", "other"];
const contentUnits: PackageContentUnitCode[] = ["kg", "t", "lb", "L", "m3", "gal_us", "bbl", "each"];
const inventoryUnits: ProductUnitCode[] = [...contentUnits, "package"];

type ProductFields = Omit<
  ProjectProduct,
  "id" | "project_id" | "configuration_version_id" | "configuration_row_version" | "prices"
>;

const emptyProduct: ProductFields = {
  item_code: "",
  item_name: "",
  alternate_name: null,
  packaging: "sack" as PackagingType,
  package_size: "",
  package_unit_code: "kg" as PackageContentUnitCode,
  inventory_applicable: true,
  inventory_unit_code: "package" as ProductUnitCode,
  specific_gravity: null,
  active: true,
};

function emptyPrice(currency: string): Omit<ProductPrice, "id" | "project_product_id"> {
  return {
    effective_from: new Date().toISOString().slice(0, 10),
    effective_to: null,
    unit_price: "",
    currency,
    price_basis_unit_code: "package",
    source: null,
  };
}

export default function ProductPricingGrid({
  configuration,
  currency,
  session,
  disabled,
  onPendingChange,
  onSaved,
}: Props) {
  const [products, setProducts] = useState<ProjectProduct[]>([]);
  const [newProduct, setNewProduct] = useState<ProductFields>(emptyProduct);
  const [priceDrafts, setPriceDrafts] = useState<Record<string, ReturnType<typeof emptyPrice>>>({});
  const [message, setMessage] = useState("Loading products…");
  const pendingRef = useRef(false);
  const configurationVersionRef = useRef(configuration.row_version);

  useEffect(() => {
    api.listProducts(session, configuration.project_id, configuration.id)
      .then((items) => {
        setProducts(items);
        setMessage(items.length ? "Product authority loaded" : "Add at least one active product.");
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "Unable to load products."));
  }, [configuration.id, configuration.project_id, session]);

  useEffect(() => {
    configurationVersionRef.current = configuration.row_version;
  }, [configuration.row_version]);

  function currentConfiguration() {
    return { ...configuration, row_version: configurationVersionRef.current };
  }

  function recordSaved(rowVersion: number) {
    configurationVersionRef.current = rowVersion;
    onSaved(rowVersion);
  }

  async function run(operation: () => Promise<void>) {
    if (disabled || pendingRef.current) return;
    pendingRef.current = true;
    onPendingChange(true);
    setMessage("Saving product configuration…");
    try {
      await operation();
      setMessage("Product configuration saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Product configuration failed");
    } finally {
      pendingRef.current = false;
      onPendingChange(false);
    }
  }

  function replaceProduct(saved: ProjectProduct) {
    setProducts((items) => items.map((item) => item.id === saved.id ? saved : item));
    recordSaved(saved.configuration_row_version);
  }

  function updateProduct(id: string, patch: Partial<ProjectProduct>) {
    if (disabled || pendingRef.current) return;
    setProducts((items) => items.map((item) => item.id === id ? { ...item, ...patch } : item));
  }

  return (
    <section className="product-section" aria-labelledby="products-heading">
      <div className="panel-heading">
        <div><span className="eyebrow">Configuration authority</span><h2 id="products-heading">Products and effective prices</h2></div>
        <span className="save-state">{message}</span>
      </div>
      <p className="muted">Package content, inventory applicability, and price basis are explicit. Effective-to dates are exclusive. Starting stock and inventory movements are intentionally unavailable in this slice.</p>

      <div className="product-grid" role="table" aria-label="Project products and pricing">
        <div className="product-grid-header" role="row">
          <span>Code / product</span><span>Package content</span><span>Inventory unit</span><span>SG</span><span>Status</span><span>Actions</span>
        </div>
        {products.map((product) => (
          <div className="product-grid-row" role="row" key={product.id}>
            <div><label>Item code<input value={product.item_code} disabled={disabled} onChange={(event) => updateProduct(product.id, { item_code: event.target.value })} /></label><label>Product name<input value={product.item_name} disabled={disabled} onChange={(event) => updateProduct(product.id, { item_name: event.target.value })} /></label></div>
            <div className="compact-fields"><label>Packaging<select value={product.packaging} disabled={disabled} onChange={(event) => updateProduct(product.id, { packaging: event.target.value as PackagingType })}>{packagingTypes.map((item) => <option key={item}>{item}</option>)}</select></label><label>Size<input inputMode="decimal" value={product.package_size} disabled={disabled} onChange={(event) => updateProduct(product.id, { package_size: event.target.value })} /></label><label>Unit<select value={product.package_unit_code} disabled={disabled} onChange={(event) => updateProduct(product.id, { package_unit_code: event.target.value as PackageContentUnitCode })}>{contentUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label></div>
            <div><label className="default-choice"><input type="checkbox" checked={product.inventory_applicable} disabled={disabled} onChange={(event) => updateProduct(product.id, { inventory_applicable: event.target.checked, inventory_unit_code: event.target.checked ? "package" : null })} /> Inventory applicable</label><label>Inventory unit<select value={product.inventory_unit_code ?? ""} disabled={disabled || !product.inventory_applicable} onChange={(event) => updateProduct(product.id, { inventory_unit_code: event.target.value as ProductUnitCode })}><option value="" disabled>Select unit</option>{inventoryUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label></div>
            <label>Specific gravity (optional)<input inputMode="decimal" placeholder="Unavailable" value={product.specific_gravity ?? ""} disabled={disabled} onChange={(event) => updateProduct(product.id, { specific_gravity: event.target.value || null })} /></label>
            <label className="default-choice"><input type="checkbox" checked={product.active} disabled={disabled} onChange={(event) => updateProduct(product.id, { active: event.target.checked })} /> Active</label>
            <div className="product-actions"><button className="button secondary" disabled={disabled} onClick={() => void run(async () => replaceProduct(await api.updateProduct(session, currentConfiguration(), product)))}>Save product</button><button className="button danger" disabled={disabled} onClick={() => void run(async () => { const result = await api.deleteProduct(session, currentConfiguration(), product.id); setProducts((items) => items.filter((item) => item.id !== product.id)); recordSaved(result.configuration_row_version); })}>Remove</button></div>

            <div className="price-history">
              <strong>Effective price history ({currency})</strong>
              {product.prices.length === 0 ? <span className="state-badge state-incomplete">Price required</span> : product.prices.map((price) => (
                <div className="price-row" key={price.id}><span>{price.effective_from} → {price.effective_to ?? "open"}</span><span>{price.unit_price} {price.currency} / {price.price_basis_unit_code}</span><button className="button danger" disabled={disabled} onClick={() => void run(async () => replaceProduct(await api.deleteProductPrice(session, currentConfiguration(), price.id)))}>Remove price</button></div>
              ))}
              <div className="price-row price-entry">
                <label>From<input type="date" disabled={disabled} value={(priceDrafts[product.id] ?? emptyPrice(currency)).effective_from} onChange={(event) => setPriceDrafts((drafts) => ({ ...drafts, [product.id]: { ...(drafts[product.id] ?? emptyPrice(currency)), effective_from: event.target.value } }))} /></label>
                <label>To (exclusive)<input type="date" disabled={disabled} value={(priceDrafts[product.id] ?? emptyPrice(currency)).effective_to ?? ""} onChange={(event) => setPriceDrafts((drafts) => ({ ...drafts, [product.id]: { ...(drafts[product.id] ?? emptyPrice(currency)), effective_to: event.target.value || null } }))} /></label>
                <label>Unit price ({currency})<input inputMode="decimal" disabled={disabled} value={(priceDrafts[product.id] ?? emptyPrice(currency)).unit_price} onChange={(event) => setPriceDrafts((drafts) => ({ ...drafts, [product.id]: { ...(drafts[product.id] ?? emptyPrice(currency)), unit_price: event.target.value } }))} /></label>
                <label>Per<select disabled={disabled} value={(priceDrafts[product.id] ?? emptyPrice(currency)).price_basis_unit_code} onChange={(event) => setPriceDrafts((drafts) => ({ ...drafts, [product.id]: { ...(drafts[product.id] ?? emptyPrice(currency)), price_basis_unit_code: event.target.value as ProductUnitCode } }))}>{inventoryUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label>
                <button className="button secondary" disabled={disabled || !(priceDrafts[product.id] ?? emptyPrice(currency)).unit_price} onClick={() => void run(async () => { const saved = await api.createProductPrice(session, currentConfiguration(), product.id, priceDrafts[product.id] ?? emptyPrice(currency)); replaceProduct(saved); setPriceDrafts((drafts) => ({ ...drafts, [product.id]: emptyPrice(currency) })); })}>Add price</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <fieldset className="new-product" disabled={disabled}>
        <legend>Add project product</legend>
        <div className="form-grid">
          <label>Item code<input value={newProduct.item_code} onChange={(event) => setNewProduct({ ...newProduct, item_code: event.target.value })} /></label>
          <label>Product name<input value={newProduct.item_name} onChange={(event) => setNewProduct({ ...newProduct, item_name: event.target.value })} /></label>
          <label>Packaging<select value={newProduct.packaging} onChange={(event) => setNewProduct({ ...newProduct, packaging: event.target.value as PackagingType })}>{packagingTypes.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>Package size<input inputMode="decimal" value={newProduct.package_size} onChange={(event) => setNewProduct({ ...newProduct, package_size: event.target.value })} /></label>
          <label>Package unit<select value={newProduct.package_unit_code} onChange={(event) => setNewProduct({ ...newProduct, package_unit_code: event.target.value as PackageContentUnitCode })}>{contentUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label>
          <label>Inventory unit<select value={newProduct.inventory_unit_code ?? ""} onChange={(event) => setNewProduct({ ...newProduct, inventory_unit_code: event.target.value as ProductUnitCode })}>{inventoryUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label>
          <label>Specific gravity (optional)<input inputMode="decimal" placeholder="Unavailable" value={newProduct.specific_gravity ?? ""} onChange={(event) => setNewProduct({ ...newProduct, specific_gravity: event.target.value || null })} /></label>
        </div>
        <button className="button primary" disabled={disabled || !newProduct.item_code || !newProduct.item_name || !newProduct.package_size} onClick={() => void run(async () => { const saved = await api.createProduct(session, currentConfiguration(), newProduct); setProducts((items) => [...items, saved]); recordSaved(saved.configuration_row_version); setNewProduct(emptyProduct); })}>Add product</button>
      </fieldset>
    </section>
  );
}
