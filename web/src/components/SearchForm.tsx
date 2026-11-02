import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const searchSchema = z.object({
  service: z.string().optional(),
  trace_id: z.string().optional(),
  q: z.string().optional(),
  level: z.string().optional(),
  to: z.string().optional(),
  from: z.string().optional(),
});

export type SearchFormValues = z.infer<typeof searchSchema>;

export function SearchForm({
  defaultValues,
  onSubmit,
}: {
  defaultValues?: Partial<SearchFormValues>;
  onSubmit: (values: SearchFormValues) => void;
}) {
  const form = useForm<SearchFormValues>({
    resolver: zodResolver(searchSchema),
    defaultValues: { service: "", trace_id: "", q: "", level: "", from: "", to: "", ...defaultValues },
  });

  return (
    <form
      onSubmit={form.handleSubmit(onSubmit)}
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end"
    >
      <div className="space-y-1.5">
        <Label htmlFor="service">Service</Label>
        <Input id="service" placeholder="vd. demo-web" {...form.register("service")} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="trace_id">Trace ID</Label>
        <Input id="trace_id" placeholder="trace_id" className="font-mono" {...form.register("trace_id")} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="level">Mức độ</Label>
        <Select value={form.watch("level") || "all"} onValueChange={(v) => form.setValue("level", v === "all" ? "" : v)}>
          <SelectTrigger id="level"><SelectValue placeholder="Tất cả mức độ" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tất cả</SelectItem>
            {["DEBUG", "INFO", "WARN", "ERROR", "FATAL"].map((item) => (
              <SelectItem value={item} key={item}>{item}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="q">Từ khoá</Label>
        <Input id="q" placeholder="trong message" {...form.register("q")} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="from">Từ thời điểm</Label>
        <Input id="from" type="datetime-local" {...form.register("from")} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="to">Đến thời điểm</Label>
        <Input id="to" type="datetime-local" {...form.register("to")} />
      </div>
      <Button type="submit" className="gap-2">
        <Search className="h-4 w-4" />
        Tìm kiếm
      </Button>
    </form>
  );
}
