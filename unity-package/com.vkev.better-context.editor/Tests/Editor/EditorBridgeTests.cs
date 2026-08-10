using System;
using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace VKev.BetterContext.Tests
{
    public sealed class EditorBridgeTests
    {
        private const string AssetPath = "Assets/BetterContextEditorBridgeTest.png";

        [SetUp]
        public void SetUp()
        {
            Texture2D texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            texture.SetPixels(new[] { Color.red, Color.green, Color.blue, Color.white });
            texture.Apply();
            File.WriteAllBytes(AssetPath, texture.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(texture);
            AssetDatabase.ImportAsset(AssetPath, ImportAssetOptions.ForceSynchronousImport);
            TextureImporter importer = (TextureImporter)AssetImporter.GetAtPath(AssetPath);
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            importer.spritePixelsPerUnit = 100f;
            importer.mipmapEnabled = false;
            importer.SaveAndReimport();
        }

        [TearDown]
        public void TearDown()
        {
            AssetDatabase.DeleteAsset(AssetPath);
        }

        [Test]
        public void LoadAllAssetsReturnsSpriteWithStableLocalId()
        {
            Sprite sprite = AssetDatabase.LoadAllAssetsAtPath(AssetPath).OfType<Sprite>().Single();

            bool resolved = AssetDatabase.TryGetGUIDAndLocalFileIdentifier(
                sprite,
                out string guid,
                out long localId);

            Assert.That(resolved, Is.True);
            Assert.That(guid, Has.Length.EqualTo(32));
            Assert.That(localId, Is.Not.Zero);
        }

        [Test]
        public void MonoScriptGetClassResolvesQualifiedType()
        {
            BridgeProbe probe = ScriptableObject.CreateInstance<BridgeProbe>();
            MonoScript script = MonoScript.FromScriptableObject(probe);

            Type resolved = script.GetClass();

            UnityEngine.Object.DestroyImmediate(probe);
            Assert.That(resolved, Is.EqualTo(typeof(BridgeProbe)));
        }

        [Test]
        public void RequestHandlerWritesImporterAndSubassetFacts()
        {
            string directory = Path.Combine("Library", "BetterContextEditorBridgeTests");
            Directory.CreateDirectory(directory);
            string requestPath = Path.GetFullPath(Path.Combine(directory, "request.json"));
            string responsePath = Path.GetFullPath(Path.Combine(directory, "snapshot.json"));
            string escapedResponse = responsePath.Replace("\\", "/");
            File.WriteAllText(
                requestPath,
                "{\"schema_version\":\"1.0.0\",\"bridge_version\":\"1.6.0\","
                + "\"nonce\":\"editmode\",\"source_hash\":\"source\","
                + "\"package_lock_hash\":\"packages\",\"response_path\":\""
                + escapedResponse
                + "\"}");

            EditorBridge.ExportRequestForTests(requestPath);

            string snapshot = File.ReadAllText(responsePath);
            StringAssert.Contains("\"nonce\": \"editmode\"", snapshot);
            StringAssert.Contains("\"path\": \"Assets/BetterContextEditorBridgeTest.png\"", snapshot);
            StringAssert.Contains("\"name\": \"pixels_per_unit\"", snapshot);
            StringAssert.Contains("\"type_name\": \"UnityEngine.Sprite\"", snapshot);
        }
    }
}
