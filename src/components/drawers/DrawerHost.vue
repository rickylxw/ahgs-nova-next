<script setup>
import { computed } from "vue";
import { useUiStore, closeDrawer } from "../../stores/ui";
import SubDetailDrawer from "./SubDetailDrawer.vue";
import UserProfileDrawer from "./UserProfileDrawer.vue";
import HeurDetailDrawer from "./HeurDetailDrawer.vue";

const DRAWERS = {
    "sub-detail": SubDetailDrawer,
    "user-profile": UserProfileDrawer,
    "heur-detail": HeurDetailDrawer,
};

const ui = useUiStore();
const drawerComp = computed(() => (ui.drawer && DRAWERS[ui.drawer.comp]) || "div");
</script>

<template>
    <div class="drawer-mask" v-if="ui.drawer" @click="closeDrawer()"></div>
    <aside class="drawer" v-if="ui.drawer">
        <component :is="drawerComp" v-bind="ui.drawer.props"
            :key="ui.drawer.comp + ':' + JSON.stringify(ui.drawer.props ?? {})" />
    </aside>
</template>
