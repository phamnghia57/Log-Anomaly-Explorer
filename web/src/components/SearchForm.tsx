import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const searchSchema = z.object({
  service: z.string().optional(),
  trace_id: z.string().optional(),
  q: z.string().optional(),
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
    defaultValues: { service: "", trace_id: "", q: "", from: "", ...defaultValues },
  });

  return (
    <form
      onSubmit={form.handleSubmit(onSubmit)}
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-end"
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
        <Label htmlFor="q">Từ khoá</Label>
        <Input id="q" placeholder="trong message" {...form.register("q")} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="from">Từ thời điểm</Label>
        <Input id="from" type="datetime-local" {...form.register("from")} />
      </div>
      <Button type="submit" className="gap-2">
        <Search className="h-4 w-4" />
        Tìm kiếm
      </Button>
    </form>
  );
}
