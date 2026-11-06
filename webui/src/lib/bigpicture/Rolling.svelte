<script lang="ts">
  /**
   * A figure on its wheels (components/Odometer.svelte), rolling up from noughts as
   * it arrives and to each new value after. The digits move by transform, on the
   * graphics card. A number counted up in text, changed every frame for a second,
   * had the whole card it sits in painted again every frame, and a page of a dozen
   * of them dropped frames on the laptop's iGPU each time it opened.
   */
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import Odometer from "../components/Odometer.svelte";
  import { motionEnabled } from "../stores";
  import { compact } from "./scenes";

  let { value = 0, delay = 140 }: { value?: number; delay?: number } = $props();

  let ready = $state(false);
  onMount(() => {
    if (!get(motionEnabled)) {
      ready = true;
      return;
    }
    const t = setTimeout(() => (ready = true), delay);
    return () => clearTimeout(t);
  });
  const text = $derived(ready ? compact(value) : compact(value).replace(/\d/g, "0"));
</script>

<Odometer value={text} />
