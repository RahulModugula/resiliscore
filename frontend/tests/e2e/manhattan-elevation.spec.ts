import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { assessManhattanProperty } from "../../src/lib/manhattan/assessment";
import type { NeighborhoodDetail } from "../../src/lib/manhattan/types";

for(const viewport of [{name:"desktop",width:1440,height:1000},{name:"mobile",width:390,height:844}]) {
test(`${viewport.name}: native USGS terrain upgrades the real building view and retains offline fallback`,async({page})=>{
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await page.setViewportSize(viewport);
  const detail:NeighborhoodDetail=JSON.parse(await readFile("public/manhattan/neighborhoods/MN0101.json","utf8"));
  const building=detail.buildings.find(b=>b.id==="441")!;
  const result=await assessManhattanProperty(building,{preferLive:false});
  await page.addInitScript(result=>sessionStorage.setItem("resiliscore:manhattan:assessment:v1:441",JSON.stringify({savedAt:Date.now(),result})),result);
  let unavailable=true, release!:()=>void;
  const held=new Promise<void>(resolve=>{release=resolve;});
  const response=JSON.parse(await readFile("tests/fixtures/elevation/usgs-block-441.json","utf8")).response;
  await page.route("https://elevation.nationalmap.gov/**",async route=>{
    if(unavailable) return route.abort("internetdisconnected");
    if(route.request().url().includes("/exportImage?")) {
      await held;
      return route.fulfill({json:response});
    }
    return route.fulfill({path:"tests/fixtures/elevation/usgs-block-441.tif",contentType:"image/tiff"});
  });
  await page.goto("/assessment?property=441");
  const block=page.getByRole("region",{name:"Building block context"});
  const status=block.getByTestId("block-elevation-status");
  await expect(status).toContainText("10 m cached ground grid");
  await expect(status).toContainText("Finer terrain unavailable");
  await expect(block.getByTestId("selected-building-marker")).toHaveAttribute("data-property-id","441");
  unavailable=false;
  await status.getByRole("button",{name:"Retry finer terrain"}).click();
  await expect(status).toContainText("Loading finer terrain");
  const canvas=block.locator("canvas");
  await expect(canvas).toBeVisible();
  const box=(await canvas.boundingBox())!;
  await canvas.scrollIntoViewIfNeeded();
  const visibleBox=(await canvas.boundingBox())!;
  await page.mouse.move(visibleBox.x+box.width*.4,visibleBox.y+box.height*.5);
  await page.mouse.down();
  await page.mouse.move(visibleBox.x+box.width*.7,visibleBox.y+box.height*.55,{steps:20});
  await page.mouse.up();
  const marker=block.getByTestId("selected-building-marker");
  let previous=await marker.boundingBox(), stable=0;
  await expect.poll(async()=>{
    const current=await marker.boundingBox();
    stable=current && previous && Math.hypot(current.x-previous.x,current.y-previous.y)<.5 ? stable+1 : 0;
    previous=current;
    return stable;
  },{message:"orbit damping settles before comparing refinement",intervals:[100,200,300]}).toBeGreaterThanOrEqual(3);
  await page.screenshot({path:test.info().outputPath("cached-terrain.png"),fullPage:true});
  const before=await block.getByTestId("selected-building-marker").boundingBox();
  release();
  await expect(status).toContainText("1.0 m ground grid",{timeout:15000});
  await expect(block.getByText(/Ground at the building base:/)).toContainText("First-floor elevation remains unknown");
  await expect(block.getByTestId("selected-building-marker")).toBeVisible();
  const after=await block.getByTestId("selected-building-marker").boundingBox();
  expect(Math.abs(after!.x-before!.x)).toBeLessThan(25);
  await page.screenshot({path:test.info().outputPath("detailed-terrain.png"),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole("tab",{name:"Model Validation",exact:true}).click();
  await page.getByRole("tab",{name:"Underwriting copilot",exact:true}).click();
  await expect(status).toContainText("1.0 m ground grid");
  expect(errors).toEqual([]);
});
}

test("a real footprint with conflicting ground is flagged without changing recorded height",async({page})=>{
  const overview:NeighborhoodDetail=JSON.parse(await readFile("public/manhattan/overview.json","utf8"));
  const building=overview.buildings.find(b=>b.id==="308707")!;
  const result=await assessManhattanProperty(building,{preferLive:false});
  await page.addInitScript(({id,result})=>sessionStorage.setItem(`resiliscore:manhattan:assessment:v1:${id}`,JSON.stringify({savedAt:Date.now(),result})),{id:building.id,result});
  await page.route("https://elevation.nationalmap.gov/**",route=>route.abort("internetdisconnected"));
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await page.goto(`/assessment?property=${building.id}`);
  const block=page.getByRole("region",{name:"Building block context"});
  await expect(block.getByRole("status").filter({hasText:"Ground samples exceed this building"})).toBeVisible();
  await expect(block.getByText("21.2 m",{exact:true})).toBeVisible();
  await expect(block.getByText(/Historical terrain can retain pits/)).toBeVisible();
  await expect(block.getByTestId("selected-building-marker")).toHaveAttribute("data-property-id",building.id);
  expect(errors).toEqual([]);
});

for(const viewport of [{name:"desktop",width:1440,height:1000},{name:"mobile",width:390,height:844}]) {
test(`${viewport.name}: exact tunnel crossing retains a separate bridge deck and unresolved building outline`,async({page})=>{
  test.setTimeout(60000);
  await page.setViewportSize(viewport);
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  const detail:NeighborhoodDetail=JSON.parse(await readFile("public/manhattan/neighborhoods/MN0603.json","utf8"));
  const building=detail.buildings.find(b=>b.id==="412518")!;
  const result=await assessManhattanProperty(building,{preferLive:false});
  await page.addInitScript(result=>sessionStorage.setItem("resiliscore:manhattan:assessment:v1:412518",JSON.stringify({savedAt:Date.now(),result})),result);
  const response=JSON.parse(await readFile("tests/fixtures/elevation/usgs-block-412518.json","utf8")).response;
  const bundle=JSON.parse(await readFile("public/manhattan/context/transport-decks.json","utf8"));
  let deckVisible=false;
  await page.route("**/manhattan/context/transport-decks.json",route=>route.fulfill({json:{...bundle,decks:deckVisible ? bundle.decks : []}}));
  await page.route("https://elevation.nationalmap.gov/**",route=>route.request().url().includes("/exportImage?") ? route.fulfill({json:response}) : route.fulfill({path:"tests/fixtures/elevation/usgs-block-412518.tif",contentType:"image/tiff"}));
  const block=page.getByRole("region",{name:"Building block context"});
  const marker=block.getByTestId("selected-building-marker");
  for(const corrected of [false,true]) {
    deckVisible=corrected;
    await page.goto("/assessment?property=412518");
    await expect(block.getByTestId("block-elevation-status")).toContainText("1.0 m ground grid · USGS 3DEP");
    await expect(marker).toBeVisible();
    await expect(marker).toHaveAttribute("data-property-id","412518");
    await expect(block.getByText("5.8 m",{exact:true})).toBeVisible();
    await expect(block.getByText("Unresolved across ground levels",{exact:true})).toBeVisible();
    await expect(block.getByText(/Ground at the building base:/)).toContainText("recorded 6.1 m source base");
    await expect(block.getByRole("button",{name:"Try 2021 terrain"})).toHaveCount(0);
    if(corrected) await expect(block.getByText(/Bridge decks use separate NYC planimetric heights/)).toBeVisible();
    await page.waitForTimeout(800);
    await block.locator("canvas").screenshot({path:test.info().outputPath(corrected ? "sourced-bridge.png" : "bare-earth-road-drape.png")});
  }
  const canvas=block.locator("canvas");
  await canvas.scrollIntoViewIfNeeded();
  const box=(await canvas.boundingBox())!;
  await page.mouse.move(box.x+box.width*.4,box.y+box.height*.5);
  await page.mouse.down();await page.mouse.move(box.x+box.width*.7,box.y+box.height*.5,{steps:15});await page.mouse.up();
  await page.mouse.wheel(0,-80);
  await page.waitForTimeout(1000);
  await canvas.screenshot({path:test.info().outputPath("sourced-bridge-orbit.png")});
  await block.getByRole("button",{name:"Reset block view"}).click();
  await page.getByRole("button",{name:"Use light theme"}).click();
  await page.getByRole("tab",{name:"Model Validation",exact:true}).click();
  await page.getByRole("tab",{name:"Underwriting copilot",exact:true}).click();
  await expect(block.getByText(/Bridge decks use separate NYC planimetric heights/)).toBeVisible();
  await expect(marker).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
}
