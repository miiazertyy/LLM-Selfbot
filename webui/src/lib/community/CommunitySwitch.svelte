<script lang="ts">
  /** Yours or the community's, at the top of the Profiles page. The pill slides, with its own sound (Segmented). */
  import Segmented from "../components/Segmented.svelte";
  import { profilesView } from "./store";

  let { updates = 0 }: { /** Your profiles with a newer version in the community: said on the switch. */ updates?: number } = $props();

  const options = $derived([
    { id: "yours", label: "Yours", icon: "layers" },
    { id: "community", label: updates ? `Community · ${updates} new` : "Community", icon: "globe" },
  ]);
</script>

<div class="cs">
  <Segmented label="Your profiles or the community's" options={options} value={$profilesView}
             onchange={(id) => profilesView.set(id === "community" ? "community" : "yours")} />
</div>

<style>
  .cs { display: flex; max-width: 380px; margin: 0 0 16px; }
  .cs :global(> *) { flex: 1; }
</style>
