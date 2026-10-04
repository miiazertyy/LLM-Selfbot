<script lang="ts">
  /**
   * The issues belonging to the page you are currently on.
   *
   * The sidebar dot tells you WHICH tab has a problem; this tells you where on
   * that tab, so arriving does not turn into hunting for the right control.
   *
   * Rendered once in App.svelte above the routed page, so every tab gets it
   * without each page having to remember to include it.
   */
  import { health } from "../stores";
  import IssueList from "./IssueList.svelte";

  let { route } = $props<{ route: string }>();

  const mine = $derived(($health.issues ?? []).filter((i) => i.route === route));
</script>

<IssueList issues={mine} here={route} />
