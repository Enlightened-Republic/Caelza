// The Shop (vision M8): the packs in looks/catalog.json. A free pack joins
// the wardrobe with one tap and its pieces appear in every agent's
// customizer; a "soon" pack is announced; a priced pack will take an unlock
// code once the gateway can verify one. The wardrobe lives on the Runtime
// (/api/looks/wardrobe), so it is the same on every device.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, Clock, Plus, Shirt } from "lucide-react";

import { Badge, Button, PageHeader } from "@/components/ui";
import { getWardrobe, putWardrobe } from "@/lib/api";
import { basePath } from "@/lib/basePath";
import { t } from "@/lib/i18n";
import { catalog } from "@/looks/Look";
import { STARTER, ownedPacks, priceLabel, sheetUrl, type CatalogPack, type Wardrobe } from "@/looks/looks.logic";

const MUTED = { color: "var(--pc-text-muted)" } as const;

export default function Shop() {
  const [wardrobe, setWardrobe] = useState<Wardrobe | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getWardrobe()
      .then((w) => {
        if (!cancelled) setWardrobe(w);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setWardrobe({ version: 1, packs: [] });
          setError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const owned = useMemo(() => ownedPacks(catalog, wardrobe), [wardrobe]);

  const change = async (pack: CatalogPack, add: boolean) => {
    if (busy) return;
    setBusy(pack.id);
    setError(null);
    const current = wardrobe?.packs ?? [];
    const next = add ? [...current.filter((p) => p !== pack.id), pack.id] : current.filter((p) => p !== pack.id);
    try {
      setWardrobe(await putWardrobe({ version: 1, packs: next }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <PageHeader
        title={t("shop.title")}
        description={t("shop.description")}
        actions={
          <Link to="/looks">
            <Button variant="ghost" size="sm">
              <Shirt className="h-4 w-4" />
              {t("shop.dress_link")}
            </Button>
          </Link>
        }
      />
      {error ? (
        <div className="text-sm" role="alert" style={{ color: "var(--color-status-error)" }}>
          {t("shop.failed")} {error}
        </div>
      ) : null}
      <div className="space-y-4">
        {catalog.packs.map((pack) => {
          const isOwned = owned.has(pack.id);
          const count = catalog.parts.filter((p) => p.pack === pack.id).length;
          return (
            <section key={pack.id} className="card cz-pack">
              <div className="cz-pack-sheet">
                {pack.status === "available" ? (
                  <img src={sheetUrl(basePath, pack.id)} alt="" className="cz-look" loading="lazy" />
                ) : (
                  <div className="cz-pack-soon">
                    <Clock className="h-6 w-6" aria-hidden="true" />
                  </div>
                )}
              </div>
              <div className="cz-pack-body">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-base font-semibold text-pc-text">{pack.name}</h2>
                  <Badge tone={pack.price === "free" ? "ok" : "neutral"}>{pack.price === "free" ? t("shop.free") : priceLabel(pack)}</Badge>
                  {pack.status === "soon" ? <Badge tone="neutral">{t("shop.soon")}</Badge> : null}
                  {count ? (
                    <span className="text-xs" style={MUTED}>
                      {count} {t("shop.pieces")}
                    </span>
                  ) : null}
                </div>
                <p className="text-sm" style={MUTED}>
                  {pack.blurb}
                </p>
                <div className="flex items-center gap-2 flex-wrap">
                  {pack.id === STARTER ? (
                    <Button variant="ghost" size="sm" disabled>
                      <Check className="h-4 w-4" />
                      {t("shop.always_yours")}
                    </Button>
                  ) : pack.status === "soon" ? (
                    <Button variant="ghost" size="sm" disabled>
                      <Clock className="h-4 w-4" />
                      {t("shop.soon")}
                    </Button>
                  ) : isOwned ? (
                    <>
                      <Button variant="ghost" size="sm" disabled>
                        <Check className="h-4 w-4" />
                        {t("shop.in_wardrobe")}
                      </Button>
                      <button type="button" className="cz-btn-text" disabled={busy !== null} onClick={() => void change(pack, false)}>
                        {t("shop.remove")}
                      </button>
                    </>
                  ) : pack.price === "free" ? (
                    <Button variant="primary" size="sm" disabled={busy !== null || wardrobe === null} onClick={() => void change(pack, true)}>
                      <Plus className="h-4 w-4" />
                      {busy === pack.id ? t("shop.adding") : t("shop.add")}
                    </Button>
                  ) : (
                    <label className="flex items-center gap-2 text-xs" style={MUTED}>
                      {t("shop.code_label")}
                      <input className="cz-input" style={{ height: 36, width: 160 }} disabled placeholder="XXXX-XXXX" />
                      <span>{t("shop.codes_soon")}</span>
                    </label>
                  )}
                </div>
              </div>
            </section>
          );
        })}
      </div>
      <div className="text-xs" style={MUTED}>
        {t("shop.updated")} {catalog.updated}.
      </div>
    </div>
  );
}
