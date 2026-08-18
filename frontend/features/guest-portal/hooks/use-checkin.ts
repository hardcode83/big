"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { getGuestPortalDataSource, type GuestPortalDTOs } from "../data";
import { guestKeys } from "./query-keys";
import { retryPolicy } from "@/lib/api/retry-policy";
export function useCheckinStatus(token: string) { return useQuery({ queryKey: guestKeys.checkin(token), queryFn: () => getGuestPortalDataSource().getCheckinStatus(token), retry: retryPolicy }); }
export function useSubmitCheckin(token: string) { return useMutation({ mutationFn: (data: GuestPortalDTOs.SubmitCheckin) => getGuestPortalDataSource().submitCheckin(token, data), retry: false }); }
