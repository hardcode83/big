"use client";
import { useQuery } from "@tanstack/react-query";
import { getGuestPortalDataSource } from "../data";
import { guestKeys } from "./query-keys";
import { retryPolicy } from "@/lib/api/retry-policy";
export function useStayInfo(token: string) { return useQuery({ queryKey: guestKeys.info(token), queryFn: () => getGuestPortalDataSource().getStayInfo(token), retry: retryPolicy }); }
