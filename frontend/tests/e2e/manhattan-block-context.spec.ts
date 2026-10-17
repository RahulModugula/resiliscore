import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { assessManhattanProperty } from "../../src/lib/manhattan/assessment";
import type { NeighborhoodDetail } from "../../src/lib/manhattan/types";

async function selectedProperty() {
  const detail:NeighborhoodDetail=JSON.parse(await readFile(`${process.cwd()}/public/manhattan/neighborhoods/MN0101.json`,"utf8"));
  return detail.buildings.find(b=>b.id==="441")!;
}

test("assessment shows street address, adjoining buildings and measured block elevation offline",async({page})=>{
  const building=await selectedProperty();
  const result=await assessManhattanProperty(building,{preferLive:false});
  await page.addInitScript(({id,result})=>sessionStorage.setItem(`resiliscore:manhattan:assessment:v1:${id}`,JSON.stringify({savedAt:Date.now(),result})),{id:building.id,result});
  await page.route("**/v1/**",route=>route.abort("connectionrefused"));
  await page.goto(`/assessment?property=${building.id}`);
  const block=page.getByRole("region",{name:"Building block context"});
  await expect(block.getByRole("heading",{name:"207 FRONT STREET",exact:true})).toBeVisible({timeout:60000});
  await expect(block.getByText("Tax block 96 and adjoining streets",{exact:true})).toBeVisible();
  await expect(block.getByText("Selected ground elevation",{exact:true})).toBeVisible();
  await expect(block.getByText(/\d+\.\d m NAVD88/, {exact:true})).toBeVisible();
  await expect(block.getByText("Building height above ground",{exact:true})).toBeVisible();
  await expect(block.locator("canvas")).toBeVisible();
  await block.getByText(/mapped buildings · .*neighboring streets/).click();
  await expect(block.getByRole("list",{name:"Surrounding building addresses"}).getByRole("listitem")).not.toHaveCount(1);
  await expect(block.getByText(/Streets:.*FULTON/)).toBeVisible();
  await expect(block.getByText(/Ground and buildings are shown at true scale/)).toBeVisible();
  await expect(page.getByRole("button",{name:/auto-bind|conditional bind/i})).toHaveCount(0);
});

test("street and elevation details survive WebGL unavailability",async({page})=>{
  const building=await selectedProperty();
  const result=await assessManhattanProperty(building,{preferLive:false});
  await page.addInitScript(({id,result})=>{
    sessionStorage.setItem(`resiliscore:manhattan:assessment:v1:${id}`,JSON.stringify({savedAt:Date.now(),result}));
    const original=HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext=function(this:HTMLCanvasElement,type,...args){
      if(String(type).includes("webgl")) return null;
      return original.call(this,type,...args);
    } as typeof HTMLCanvasElement.prototype.getContext;
  },{id:building.id,result});
  await page.goto(`/assessment?property=${building.id}`);
  const block=page.getByRole("region",{name:"Building block context"});
  await expect(block.getByRole("heading",{name:"207 FRONT STREET",exact:true})).toBeVisible({timeout:60000});
  await expect(block.getByText(/3D rendering is unavailable/)).toBeVisible();
  await expect(block.getByText(/\d+\.\d m NAVD88/, {exact:true})).toBeVisible();
  await block.getByText(/mapped buildings · .*neighboring streets/).click();
  await expect(block.getByText(/Streets:.*FULTON/)).toBeVisible();
});
