import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { IncidentDisposition, IncidentEpisode } from "@/lib/api";
import { ApiError } from "@/lib/api-base";
import { formatDateTime } from "@/lib/format";
import { useUpdateIncident } from "@/lib/queries";

const STATUS = { open: "Chưa tiếp nhận", acknowledged: "Đã tiếp nhận", resolved: "Đã đóng" };
const DISPOSITION = { confirmed_incident: "Sự cố thật", false_positive: "Báo động giả" };

function localDateInput(timestamp: string) {
  const date = new Date(timestamp);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, -1);
}

function incidentBound(original: string) {
  const initial = localDateInput(original);
  return { original, initial, value: initial };
}

function resolveBound(bound: ReturnType<typeof incidentBound>) {
  // Compare wall times in UTC so DST does not influence whether the field changed.
  if (Date.parse(`${bound.value}Z`) === Date.parse(`${bound.initial}Z`)) return bound.original;
  const edited = new Date(bound.value);
  return Number.isFinite(edited.getTime()) ? edited.toISOString() : null;
}

export function IncidentActions({ clusterId, incident }: { clusterId: string; incident: IncidentEpisode | null }) {
  const mutation = useUpdateIncident(clusterId);
  const [draft, setDraft] = useState<{
    episodeId: string; from: ReturnType<typeof incidentBound>; to: ReturnType<typeof incidentBound>;
    note: string; disposition: IncidentDisposition | "";
  } | null>(null);
  const [invalidWindow, setInvalidWindow] = useState(false);

  if (!incident) return <p className="mt-4 text-sm text-muted-foreground">Chưa tải được trạng thái xử lý sự cố.</p>;
  const staleDraft = draft !== null && (draft.episodeId !== incident.episode_id || incident.status === "resolved");
  const error = mutation.error instanceof ApiError && mutation.error.status === 409
    ? "Trạng thái sự cố đã thay đổi. Hãy kiểm tra lại đợt xử lý."
    : mutation.error ? "Không lưu được trạng thái. Vui lòng thử lại." : null;

  function resolve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft?.disposition || staleDraft || mutation.isPending) return;
    const from = resolveBound(draft.from);
    const to = resolveBound(draft.to);
    if (!from || !to || Date.parse(from) >= Date.parse(to)) {
      setInvalidWindow(true);
      return;
    }
    setInvalidWindow(false);
    mutation.mutate({
      action: "resolve", episode_id: draft.episodeId, disposition: draft.disposition,
      note: draft.note.trim(), window_from: from, window_to: to,
    }, { onSuccess: () => setDraft(null) });
  }

  return (
    <section className="mt-5 space-y-2 border-t pt-4" aria-label="Xử lý sự cố">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm font-medium">{STATUS[incident.status]}</p>
        {incident.status === "open" && (
          <Button size="sm" variant="outline" disabled={mutation.isPending}
            onClick={() => mutation.mutate({ action: "acknowledge", episode_id: incident.episode_id })}>
            Tiếp nhận
          </Button>
        )}
        {incident.status !== "resolved" && (
          <Button size="sm" disabled={mutation.isPending} onClick={() => {
            mutation.reset();
            setInvalidWindow(false);
            setDraft({
              episodeId: incident.episode_id, from: incidentBound(incident.window_from),
              to: incidentBound(incident.window_to), note: "", disposition: "",
            });
          }}>
            Đóng sự cố
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {formatDateTime(incident.window_from)} – {formatDateTime(incident.window_to)}
      </p>
      {incident.acknowledged_at && <p className="text-xs text-muted-foreground">
        {incident.acknowledged_by} tiếp nhận lúc {formatDateTime(incident.acknowledged_at)}
      </p>}
      {incident.resolved_at && <p className="text-xs text-muted-foreground">
        {incident.resolved_by} đóng lúc {formatDateTime(incident.resolved_at)}
      </p>}
      {incident.disposition && <p className="text-sm">{DISPOSITION[incident.disposition]}</p>}
      {incident.note && <p className="whitespace-pre-wrap break-words text-sm">{incident.note}</p>}
      {!draft && error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Dialog open={draft !== null} onOpenChange={(open) => {
        if (!open && !mutation.isPending) setDraft(null);
      }}>
        {draft && <DialogContent>
          <DialogTitle>Đóng sự cố</DialogTitle>
          <DialogDescription>Ghi kết luận và khoảng thời gian điều tra theo giờ địa phương.</DialogDescription>
          <form onSubmit={resolve} className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="incident-disposition">Kết luận</Label>
              <select id="incident-disposition" required className="w-full rounded-md border bg-background px-2 py-1"
                value={draft.disposition}
                onChange={(e) => setDraft({ ...draft, disposition: e.target.value as IncidentDisposition | "" })}>
                <option value="" disabled>Chọn kết luận</option>
                <option value="confirmed_incident">Sự cố thật</option>
                <option value="false_positive">Báo động giả</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="incident-from">Bắt đầu</Label>
              <Input id="incident-from" type="datetime-local" step="0.001" required value={draft.from.value}
                onChange={(e) => setDraft({ ...draft, from: { ...draft.from, value: e.target.value } })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="incident-to">Kết thúc</Label>
              <Input id="incident-to" type="datetime-local" step="0.001" required value={draft.to.value}
                onChange={(e) => setDraft({ ...draft, to: { ...draft.to, value: e.target.value } })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="incident-note">Nguyên nhân gốc hoặc lý do báo động giả</Label>
              <textarea id="incident-note" required maxLength={4000} rows={3} value={draft.note}
                className="w-full rounded-md border bg-background p-2"
                onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
            </div>
            {(invalidWindow || error || staleDraft) && <p role="alert" className="text-destructive">
              {staleDraft ? "Đợt xử lý đã thay đổi. Hãy lưu lại ghi chú trước khi đóng hộp thoại."
                : invalidWindow ? "Thời gian bắt đầu phải trước thời gian kết thúc." : error}
            </p>}
            <DialogFooter>
              <Button type="button" variant="outline" disabled={mutation.isPending}
                onClick={() => setDraft(null)}>Hủy</Button>
              <Button type="submit" disabled={mutation.isPending || staleDraft || !draft.disposition || !draft.note.trim()}>
                Lưu kết luận
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>}
      </Dialog>
    </section>
  );
}
