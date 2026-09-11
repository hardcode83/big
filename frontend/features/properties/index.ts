// The properties feature's public surface. `PropertiesView` is the App
// Router page's own component; the detail DTO/command types and the new
// data-mutating hooks are re-exported so `features/dashboard` can pre-fill
// and drive `EditPropertyForm`/the retire action without reaching into this
// feature's internals (design D3, mirroring how `dashboard` already imports
// from `@/features/incidents`).
export { PropertiesView } from "./components/list/properties-view";
export { useProperty } from "./hooks/use-property";
export { useCreateProperty } from "./hooks/use-create-property";
export {
  useUpdateProperty,
  type UpdatePropertyMutationInput,
} from "./hooks/use-update-property";
export type {
  PropertyDetailDto,
  CreatePropertyInput,
  UpdatePropertyInput,
} from "./data";
