"use client";
import { useMutation } from "@tanstack/react-query";
import { getGuestPortalDataSource, type GuestPortalDTOs } from "../data";
export function useReportIncident(token: string) { return useMutation({ mutationFn: (data: GuestPortalDTOs.ReportIncident) => getGuestPortalDataSource().reportIncident(token, data), retry: false }); }
