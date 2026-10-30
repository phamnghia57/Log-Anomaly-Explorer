import { useEffect, useRef, useState } from "react";
import { Bot, Loader2, Search, Send, Square, User } from "lucide-react";
import type { AssistantMessage } from "@/lib/api";
import { useAssistantConversation, useSendAssistantMessage } from "@/lib/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";

const TOOL_LABELS: Record<string, string> = {
  get_cluster_history: "Đang xem xu hướng anomaly score…",
  search_related_logs: "Đang tìm log liên quan…",
  list_active_clusters: "Đang kiểm tra các cụm khác đang bất thường…",
};

function MessageBubble({ message }: { message: AssistantMessage }) {
  // role=tool: ket qua AI tu tra cuu (xem query-api/src/assistant/tools.py) -
  // hien dong trang thai ngan, khong phai bubble chat.
  if (message.role === "tool") {
    return (
      <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
        <Search className="h-3 w-3 shrink-0" />
        {TOOL_LABELS[message.name ?? ""] ?? `Đang tra cứu (${message.name})…`}
      </div>
    );
  }

  // assistant message chi co tool_calls, khong co content: da hien qua dong
  // "tool" ngay sau no, khong can render bubble rong.
  if (!message.content) return null;

  const isUser = message.role === "user";
  return (
    <div className={`flex gap-2 py-1.5 ${isUser ? "flex-row-reverse" : ""}`}>
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted">
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}

// Panel dieu tra & de xuat cach sua voi AI Assistant (dong vai tro giong
// Elastic Observability AI Assistant, thu gon - xem api-contract.md muc
// "AI Assistant"). Hoi thoai duoc luu theo cluster_id, mo lai Incident View
// van thay lai cau hoi/tra loi cu.
export function AssistantPanel({ clusterId }: { clusterId: string }) {
  const [draft, setDraft] = useState("");
  const { data, isLoading, isError } = useAssistantConversation(clusterId);
  const mutation = useSendAssistantMessage(clusterId);
  const bottomRef = useRef<HTMLDivElement>(null);
  // AbortController cho nut "Dung": cho phep nguoi dung huy cau hoi dang cho
  // (vd. model dong reasoning suy luan qua lau) de hoi lai cau khac, thay vi
  // phai cho den khi request cu tu ket thuc.
  const controllerRef = useRef<AbortController | null>(null);
  const pendingTextRef = useRef("");

  const messages = data?.messages ?? [];
  const isAbortError = mutation.error instanceof DOMException && mutation.error.name === "AbortError";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, mutation.isPending]);

  // Loi that (khong phai tu nguoi dung bam Dung): tra lai noi dung da go,
  // tranh nguoi dung phai go lai tu dau khi muon thu lai (vd. timeout voi
  // cau hoi phuc tap - xem AZURE_OPENAI_TIMEOUT_SECONDS/ASSISTANT_MAX_TOOL_ROUNDS).
  useEffect(() => {
    if (mutation.isError && !isAbortError && pendingTextRef.current) {
      setDraft(pendingTextRef.current);
      pendingTextRef.current = "";
    }
  }, [mutation.isError, isAbortError]);

  const handleSend = () => {
    const text = draft.trim();
    if (!text || mutation.isPending) return;
    setDraft("");
    pendingTextRef.current = text;
    const controller = new AbortController();
    controllerRef.current = controller;
    mutation.mutate({ message: text, signal: controller.signal });
  };

  const handleStop = () => {
    controllerRef.current?.abort();
    // Tra lai noi dung da go de nguoi dung khong phai nhap lai tu dau.
    setDraft(pendingTextRef.current);
  };

  return (
    <div className="flex h-[28rem] flex-col rounded-xl border bg-card">
      <div className="border-b px-4 py-2.5">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <Bot className="h-4 w-4" />
          Điều tra với AI Assistant
        </h2>
      </div>

      <ScrollArea className="flex-1 px-4">
        {isLoading && <Skeleton className="my-3 h-16" />}

        {isError && (
          <p className="py-6 text-center text-xs text-muted-foreground">
            Không tải được hội thoại trước đó — vẫn có thể hỏi câu mới bên dưới.
          </p>
        )}

        {!isLoading && messages.length === 0 && !mutation.isPending && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Hỏi AI Assistant về nguyên nhân và cách sửa lỗi của cụm này — ví dụ
            "Lỗi này do đâu?" hoặc "Có service nào khác bị ảnh hưởng không?".
          </p>
        )}

        <div className="py-2">
          {messages.map((message, index) => (
            // Hoi thoai khong co id rieng tung message (xem contract) - dung
            // index la hop ly vi danh sach chi them vao cuoi, khong sap xep lai.
            <MessageBubble key={index} message={message} />
          ))}
        </div>

        {mutation.isPending && (
          <div className="flex items-center justify-between gap-2 py-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin" />
              AI đang điều tra… (có thể mất đến 1–2 phút với câu hỏi cần tra cứu thêm)
            </span>
            <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-xs" onClick={handleStop}>
              <Square className="h-3 w-3" />
              Dừng
            </Button>
          </div>
        )}

        {mutation.isError && !isAbortError && (
          <div className="my-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <p className="font-medium">AI Assistant chưa trả lời được câu hỏi này.</p>
            <p className="mt-0.5 text-destructive/80">
              {mutation.error instanceof Error ? mutation.error.message : "Có lỗi, thử lại."}
              {" "}— có thể do câu hỏi cần tra cứu nhiều, vượt quá thời gian chờ. Nội dung đã được
              khôi phục vào ô nhập, thử hỏi ngắn gọn/cụ thể hơn rồi gửi lại.
            </p>
          </div>
        )}

        <div ref={bottomRef} />
      </ScrollArea>

      <div className="flex items-center gap-2 border-t p-3">
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
          placeholder="Hỏi về nguyên nhân, cách sửa…"
          disabled={mutation.isPending}
        />
        <Button
          size="sm"
          onClick={handleSend}
          disabled={!draft.trim() || mutation.isPending}
          aria-label="Gửi câu hỏi"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
