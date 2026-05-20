import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CreateProductPayload, Product } from "@shared/types";
import { api } from "@renderer/lib/api";

const KEY = ["products", "list"] as const;

export function useProducts() {
  return useQuery<Product[]>({
    queryKey: KEY,
    queryFn:  () => api.products.list(),
  });
}

export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: CreateProductPayload) => api.products.create(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
