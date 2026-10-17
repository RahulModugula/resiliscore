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
