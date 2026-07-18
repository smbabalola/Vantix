import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, type Session } from "./api";
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
  onDirtyChange: (dirty: boolean) => void;
}

const packagingTypes: PackagingType[] = ["sack", "pail", "drum", "tote", "bulk", "case", "each", "other"];
const contentUnits: PackageContentUnitCode[] = ["kg", "t", "lb", "L", "m3", "gal_us", "bbl", "each"];
const inventoryUnits: ProductUnitCode[] = [...contentUnits, "package"];
const dimensions: Record<PackageContentUnitCode, "mass" | "volume" | "count"> = {
  kg: "mass", t: "mass", lb: "mass", L: "volume", m3: "volume", gal_us: "volume",
  bbl: "volume", each: "count",
};

type ProductFields = Omit<
  ProjectProduct,
  "id" | "product_definition_id" | "project_id" | "configuration_version_id" |
  "configuration_row_version" | "prices"
>;
type PriceDraft = Omit<ProductPrice, "id" | "project_product_id">;

function emptyProduct(): ProductFields {
  return {
    item_code: "",
    item_name: "",
    alternate_name: null,
    packaging: "sack",
    package_size: "",
    package_unit_code: "kg",
    inventory_applicable: true,
    inventory_unit_code: "package",
    specific_gravity: null,
    active: true,
  };
}

function emptyPrice(currency: string): PriceDraft {
  return {
    effective_from: "",
    effective_to: null,
    unit_price: "",
    currency,
    price_basis_unit_code: "package",
    source: null,
  };
}

function priceDraftIsDirty(price: PriceDraft | undefined): boolean {
  return Boolean(price && (
    price.effective_from || price.effective_to || price.unit_price || price.source ||
    price.price_basis_unit_code !== "package"
  ));
}

function compatiblePriceUnits(packageUnit: PackageContentUnitCode): ProductUnitCode[] {
  const dimension = dimensions[packageUnit];
  return ["package", ...contentUnits.filter((unit) => dimensions[unit] === dimension)];
}

function FieldError({ message }: { message?: string }) {
  return message ? <span className="field-error" role="alert">{message}</span> : null;
}

function productErrorKey(productId: string, field: string): string {
  return field.startsWith("prices.")
    ? `price:${productId}:${field.replace(/^prices\./, "")}`
    : `product:${productId}:${field}`;
}

function priceErrorKey(productId: string, field: string): string {
  return `price:${productId}:${field.replace(/^prices\./, "")}`;
}

export default function ProductPricingGrid({
  configuration,
  currency,
  session,
  disabled,
  onPendingChange,
  onSaved,
  onDirtyChange,
}: Props) {
  const [products, setProducts] = useState<ProjectProduct[]>([]);
  const [newProduct, setNewProduct] = useState<ProductFields>(emptyProduct);
  const [priceDrafts, setPriceDrafts] = useState<Record<string, PriceDraft>>({});
  const [dirtyProductIds, setDirtyProductIds] = useState<Set<string>>(new Set());
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("Loading products…");
  const savedProductsRef = useRef(new Map<string, ProjectProduct>());
  const pendingRef = useRef(false);
  const configurationVersionRef = useRef(configuration.row_version);
  const newProductDirty = JSON.stringify(newProduct) !== JSON.stringify(emptyProduct());
  const gridDirty = dirtyProductIds.size > 0 || newProductDirty ||
    Object.values(priceDrafts).some(priceDraftIsDirty);

  useEffect(() => {
    api.listProducts(session, configuration.project_id, configuration.id)
      .then((items) => {
        setProducts(items);
        savedProductsRef.current = new Map(items.map((item) => [item.id, structuredClone(item)]));
        setDirtyProductIds(new Set());
        setPriceDrafts({});
        setNewProduct(emptyProduct());
        setFieldErrors({});
        setMessage(items.length ? "Product authority loaded" : "Add at least one active product.");
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "Unable to load products."));
  }, [configuration.id, configuration.project_id, session]);

  useEffect(() => {
    configurationVersionRef.current = configuration.row_version;
  }, [configuration.row_version]);

  useEffect(() => {
    onDirtyChange(gridDirty);
  }, [gridDirty, onDirtyChange]);

  const currentConfiguration = () => ({
    ...configuration,
    row_version: configurationVersionRef.current,
  });

  function recordSaved(rowVersion: number) {
    configurationVersionRef.current = rowVersion;
    onSaved(rowVersion);
  }

  function setError(error: unknown, keyForField: (field: string) => string) {
    if (error instanceof ApiError && error.field) {
      setFieldErrors((current) => ({ ...current, [keyForField(error.field!)]: error.message }));
    }
    setMessage(error instanceof Error ? error.message : "Product configuration failed");
  }

  async function run(operation: () => Promise<void>, keyForField: (field: string) => string) {
    if (disabled || pendingRef.current) return;
    pendingRef.current = true;
    onPendingChange(true);
    setFieldErrors({});
    setMessage("Saving product configuration…");
    try {
      await operation();
      setMessage("Product configuration saved");
    } catch (error) {
      setError(error, keyForField);
    } finally {
      pendingRef.current = false;
      onPendingChange(false);
    }
  }

  function commitProduct(saved: ProjectProduct) {
    setProducts((items) => items.map((item) => item.id === saved.id ? saved : item));
    savedProductsRef.current.set(saved.id, structuredClone(saved));
    setDirtyProductIds((current) => {
      const next = new Set(current);
      next.delete(saved.id);
      return next;
    });
    recordSaved(saved.configuration_row_version);
  }

  function updateProduct(id: string, patch: Partial<ProjectProduct>) {
    if (disabled || pendingRef.current) return;
    onDirtyChange(true);
    setProducts((items) => items.map((item) => item.id === id ? { ...item, ...patch } : item));
    setDirtyProductIds((current) => new Set(current).add(id));
  }

  function discardProduct(id: string) {
    const saved = savedProductsRef.current.get(id);
    if (!saved) return;
    setProducts((items) => items.map((item) => item.id === id ? structuredClone(saved) : item));
    setDirtyProductIds((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
    setFieldErrors((current) => Object.fromEntries(
      Object.entries(current).filter(([key]) => !key.startsWith(`product:${id}:`)),
    ));
  }

  function updatePriceDraft(productId: string, patch: Partial<PriceDraft>) {
    if (disabled || pendingRef.current) return;
    onDirtyChange(true);
    setPriceDrafts((drafts) => ({
      ...drafts,
      [productId]: { ...(drafts[productId] ?? emptyPrice(currency)), ...patch },
    }));
  }

  function updateNewProduct(patch: Partial<ProductFields>) {
    if (disabled || pendingRef.current) return;
    onDirtyChange(true);
    setNewProduct((current) => ({ ...current, ...patch }));
  }

  const productRows = useMemo(() => products, [products]);

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
        {productRows.map((product) => {
          const rowDirty = dirtyProductIds.has(product.id);
          const priceDraft = priceDrafts[product.id] ?? emptyPrice(currency);
          const priceDirty = priceDraftIsDirty(priceDrafts[product.id]);
          const priceUnits = compatiblePriceUnits(product.package_unit_code);
          return (
            <div className="product-grid-row" role="row" key={product.id}>
              <div>
                <label>Item code<input value={product.item_code} disabled={disabled} onChange={(event) => updateProduct(product.id, { item_code: event.target.value })} /><FieldError message={fieldErrors[`product:${product.id}:item_code`]} /></label>
                <label>Product name<input value={product.item_name} disabled={disabled} onChange={(event) => updateProduct(product.id, { item_name: event.target.value })} /><FieldError message={fieldErrors[`product:${product.id}:item_name`]} /></label>
              </div>
              <div className="compact-fields">
                <label>Packaging<select value={product.packaging} disabled={disabled} onChange={(event) => updateProduct(product.id, { packaging: event.target.value as PackagingType })}>{packagingTypes.map((item) => <option key={item}>{item}</option>)}</select></label>
                <label>Size<input inputMode="decimal" value={product.package_size} disabled={disabled} onChange={(event) => updateProduct(product.id, { package_size: event.target.value })} /><FieldError message={fieldErrors[`product:${product.id}:package_size`]} /></label>
                <label>Unit<select value={product.package_unit_code} disabled={disabled} onChange={(event) => updateProduct(product.id, { package_unit_code: event.target.value as PackageContentUnitCode })}>{contentUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label>
              </div>
              <div>
                <label className="default-choice"><input type="checkbox" checked={product.inventory_applicable} disabled={disabled} onChange={(event) => updateProduct(product.id, { inventory_applicable: event.target.checked, inventory_unit_code: event.target.checked ? "package" : null })} /> Inventory applicable</label>
                <label>Inventory unit<select value={product.inventory_unit_code ?? ""} disabled={disabled || !product.inventory_applicable} onChange={(event) => updateProduct(product.id, { inventory_unit_code: event.target.value as ProductUnitCode })}><option value="" disabled>Select unit</option>{inventoryUnits.map((unit) => <option key={unit}>{unit}</option>)}</select><FieldError message={fieldErrors[`product:${product.id}:inventory_unit_code`]} /></label>
              </div>
              <label>Specific gravity (optional)<input inputMode="decimal" placeholder="Unavailable" value={product.specific_gravity ?? ""} disabled={disabled} onChange={(event) => updateProduct(product.id, { specific_gravity: event.target.value || null })} /><FieldError message={fieldErrors[`product:${product.id}:specific_gravity`]} /></label>
              <label className="default-choice"><input type="checkbox" checked={product.active} disabled={disabled} onChange={(event) => updateProduct(product.id, { active: event.target.checked })} /> Active</label>
              <div className="product-actions">
                <button className="button secondary" disabled={disabled || !rowDirty} onClick={() => void run(async () => commitProduct(await api.updateProduct(session, currentConfiguration(), product)), (field) => productErrorKey(product.id, field))}>Save product</button>
                <button className="button ghost" disabled={disabled || !rowDirty} onClick={() => discardProduct(product.id)}>Discard edits</button>
                <button className="button danger" disabled={disabled || rowDirty || priceDirty} onClick={() => void run(async () => { const result = await api.deleteProduct(session, currentConfiguration(), product.id); setProducts((items) => items.filter((item) => item.id !== product.id)); savedProductsRef.current.delete(product.id); recordSaved(result.configuration_row_version); }, (field) => productErrorKey(product.id, field))}>Remove</button>
              </div>

              <div className="price-history">
                <strong>Effective price history ({currency})</strong>
                {product.prices.length === 0 ? <span className="state-badge state-incomplete">Price required</span> : product.prices.map((price) => (
                  <div className="price-row" key={price.id}><span>{price.effective_from} → {price.effective_to ?? "open"}</span><span>{price.unit_price} {price.currency} / {price.price_basis_unit_code}</span><button className="button danger" disabled={disabled || rowDirty || priceDirty} onClick={() => void run(async () => commitProduct(await api.deleteProductPrice(session, currentConfiguration(), price.id)), (field) => priceErrorKey(product.id, field))}>Remove price</button></div>
                ))}
                <div className="price-row price-entry">
                  <label>From<input type="date" disabled={disabled || rowDirty} required value={priceDraft.effective_from} onChange={(event) => updatePriceDraft(product.id, { effective_from: event.target.value })} /><FieldError message={fieldErrors[`price:${product.id}:effective_from`]} /></label>
                  <label>To (exclusive)<input type="date" disabled={disabled || rowDirty} value={priceDraft.effective_to ?? ""} onChange={(event) => updatePriceDraft(product.id, { effective_to: event.target.value || null })} /><FieldError message={fieldErrors[`price:${product.id}:effective_to`]} /></label>
                  <label>Unit price ({currency})<input inputMode="decimal" disabled={disabled || rowDirty} value={priceDraft.unit_price} onChange={(event) => updatePriceDraft(product.id, { unit_price: event.target.value })} /><FieldError message={fieldErrors[`price:${product.id}:unit_price`]} /></label>
                  <label>Per<select disabled={disabled || rowDirty} value={priceDraft.price_basis_unit_code} onChange={(event) => updatePriceDraft(product.id, { price_basis_unit_code: event.target.value as ProductUnitCode })}>{priceUnits.map((unit) => <option key={unit}>{unit}</option>)}</select><FieldError message={fieldErrors[`price:${product.id}:price_basis_unit_code`]} /></label>
                  <button className="button secondary" disabled={disabled || rowDirty || !priceDraft.unit_price || !priceDraft.effective_from} onClick={() => void run(async () => { const saved = await api.createProductPrice(session, currentConfiguration(), product.id, priceDraft); commitProduct(saved); setPriceDrafts((drafts) => ({ ...drafts, [product.id]: emptyPrice(currency) })); }, (field) => priceErrorKey(product.id, field))}>Add price</button>
                  <button className="button ghost" disabled={disabled || !priceDirty} onClick={() => setPriceDrafts((drafts) => ({ ...drafts, [product.id]: emptyPrice(currency) }))}>Discard price draft</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <fieldset className="new-product" disabled={disabled}>
        <legend>Add project product</legend>
        <div className="form-grid">
          <label>Item code<input value={newProduct.item_code} onChange={(event) => updateNewProduct({ item_code: event.target.value })} /><FieldError message={fieldErrors["new:item_code"]} /></label>
          <label>Product name<input value={newProduct.item_name} onChange={(event) => updateNewProduct({ item_name: event.target.value })} /><FieldError message={fieldErrors["new:item_name"]} /></label>
          <label>Packaging<select value={newProduct.packaging} onChange={(event) => updateNewProduct({ packaging: event.target.value as PackagingType })}>{packagingTypes.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>Package size<input inputMode="decimal" value={newProduct.package_size} onChange={(event) => updateNewProduct({ package_size: event.target.value })} /><FieldError message={fieldErrors["new:package_size"]} /></label>
          <label>Package unit<select value={newProduct.package_unit_code} onChange={(event) => updateNewProduct({ package_unit_code: event.target.value as PackageContentUnitCode })}>{contentUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label>
          <label className="default-choice"><input type="checkbox" checked={newProduct.inventory_applicable} onChange={(event) => updateNewProduct({ inventory_applicable: event.target.checked, inventory_unit_code: event.target.checked ? "package" : null })} /> Inventory applicable</label>
          <label>Inventory unit<select value={newProduct.inventory_unit_code ?? ""} disabled={!newProduct.inventory_applicable} onChange={(event) => updateNewProduct({ inventory_unit_code: event.target.value as ProductUnitCode })}><option value="" disabled>Select unit</option>{inventoryUnits.map((unit) => <option key={unit}>{unit}</option>)}</select><FieldError message={fieldErrors["new:inventory_unit_code"]} /></label>
          <label>Specific gravity (optional)<input inputMode="decimal" placeholder="Unavailable" value={newProduct.specific_gravity ?? ""} onChange={(event) => updateNewProduct({ specific_gravity: event.target.value || null })} /><FieldError message={fieldErrors["new:specific_gravity"]} /></label>
        </div>
        <div className="button-row">
          <button className="button primary" disabled={disabled || !newProduct.item_code || !newProduct.item_name || !newProduct.package_size} onClick={() => void run(async () => { const saved = await api.createProduct(session, currentConfiguration(), newProduct); setProducts((items) => [...items, saved]); savedProductsRef.current.set(saved.id, structuredClone(saved)); recordSaved(saved.configuration_row_version); setNewProduct(emptyProduct()); }, (field) => `new:${field}`)}>Add product</button>
          <button className="button ghost" disabled={disabled || !newProductDirty} onClick={() => { setNewProduct(emptyProduct()); setFieldErrors({}); }}>Discard new product</button>
        </div>
      </fieldset>
    </section>
  );
}
